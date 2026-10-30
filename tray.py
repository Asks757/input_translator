"""系统托盘（StatusNotifierItem / SNI）。

Deepin、KDE、GNOME（装了 AppIndicator 扩展）、xfce4-statusnotifier 等现代桌面
只认 SNI + com.canonical.dbusmenu，老的 XEmbed 托盘（pystray 的 xorg 后端）
在 dde-dock 上根本不会显示。所以这里直接用 dbus-next 实现一个最小可用的 SNI
托盘项，不依赖 GTK / PyGObject。

用法：
    tray = SniTray(title, icon_pixmaps, callbacks)
    ok, detail = tray.start()      # 阻塞约 2 秒，返回是否注册成功
    ...
    tray.stop()
回调都在 dbus 线程里触发，只应往队列里塞事件，不要直接碰 Tk。
"""

import asyncio
import os
import threading

try:
    from dbus_next import Variant
    from dbus_next.aio import MessageBus
    from dbus_next.service import (
        PropertyAccess,
        ServiceInterface,
        dbus_property,
        method,
        signal,
    )

    DBUS_AVAILABLE = True
    DBUS_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - 取决于运行环境
    DBUS_AVAILABLE = False
    DBUS_IMPORT_ERROR = str(error)

WATCHER_BUS = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_IFACE = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

# 菜单项：(id, 标题, 动作名)，标题为 None 表示分隔线
MENU_ITEMS = (
    (1, "呼出悬浮窗", "overlay"),
    (2, "显示设置窗口", "settings"),
    (3, None, None),
    (4, "退出", "quit"),
)


def rgba_to_argb(image):
    """把 PIL 的 RGBA 转成 SNI 需要的 ARGB32（网络字节序）字节串。"""
    image = image.convert("RGBA")
    raw = image.tobytes()
    out = bytearray(len(raw))
    out[0::4] = raw[3::4]
    out[1::4] = raw[0::4]
    out[2::4] = raw[1::4]
    out[3::4] = raw[2::4]
    return bytes(out)


if DBUS_AVAILABLE:

    class StatusNotifierItem(ServiceInterface):
        def __init__(self, item_id, title, pixmaps, callbacks):
            super().__init__("org.kde.StatusNotifierItem")
            self._id = item_id
            self._title = title
            # dbus-next 的 STRUCT 必须是 list，不能是 tuple
            self._pixmaps = [[w, h, data] for w, h, data in (pixmaps or [])]
            self._callbacks = callbacks

        # ---- 方法 ----
        @method()
        def Activate(self, x: "i", y: "i"):
            self._callbacks.get("overlay") and self._callbacks["overlay"]()

        @method()
        def SecondaryActivate(self, x: "i", y: "i"):
            self._callbacks.get("settings") and self._callbacks["settings"]()

        @method()
        def ContextMenu(self, x: "i", y: "i"):
            # 没有 dbusmenu 的主机（部分桌面）会走这里
            self._callbacks.get("menu") and self._callbacks["menu"](x, y)

        @method()
        def Scroll(self, delta: "i", orientation: "s"):
            return

        @method()
        def ProvideXdgActivationToken(self, token: "s"):
            return

        # ---- 属性 ----
        @dbus_property(access=PropertyAccess.READ)
        def Category(self) -> "s":
            return "ApplicationStatus"

        @dbus_property(access=PropertyAccess.READ)
        def Id(self) -> "s":
            return self._id

        @dbus_property(access=PropertyAccess.READ)
        def Title(self) -> "s":
            return self._title

        @dbus_property(access=PropertyAccess.READ)
        def Status(self) -> "s":
            return "Active"

        @dbus_property(access=PropertyAccess.READ)
        def WindowId(self) -> "i":
            return 0

        @dbus_property(access=PropertyAccess.READ)
        def IconName(self) -> "s":
            return ""

        @dbus_property(access=PropertyAccess.READ)
        def IconPixmap(self) -> "a(iiay)":
            return self._pixmaps

        @dbus_property(access=PropertyAccess.READ)
        def OverlayIconName(self) -> "s":
            return ""

        @dbus_property(access=PropertyAccess.READ)
        def OverlayIconPixmap(self) -> "a(iiay)":
            return []

        @dbus_property(access=PropertyAccess.READ)
        def AttentionIconName(self) -> "s":
            return ""

        @dbus_property(access=PropertyAccess.READ)
        def AttentionIconPixmap(self) -> "a(iiay)":
            return []

        @dbus_property(access=PropertyAccess.READ)
        def AttentionMovieName(self) -> "s":
            return ""

        @dbus_property(access=PropertyAccess.READ)
        def ItemIsMenu(self) -> "b":
            return False

        @dbus_property(access=PropertyAccess.READ)
        def Menu(self) -> "o":
            return MENU_PATH

        @dbus_property(access=PropertyAccess.READ)
        def ToolTip(self) -> "(sa(iiay)ss)":
            return ["", self._pixmaps, self._title, ""]

    class DBusMenu(ServiceInterface):
        """com.canonical.dbusmenu 的最小实现，够 dde-dock / KDE 渲染右键菜单。"""

        def __init__(self, on_action):
            super().__init__("com.canonical.dbusmenu")
            self._on_action = on_action
            self._revision = 1

        def _props(self, item_id):
            label = dict((i, t) for i, t, _ in MENU_ITEMS if i is not None)
            action = dict((i, a) for i, _, a in MENU_ITEMS if a)
            if item_id == 0:
                return {}
            if item_id in action:
                return {
                    "label": Variant("s", label[item_id]),
                    "enabled": Variant("b", True),
                    "visible": Variant("b", True),
                    "type": Variant("s", "standard"),
                }
            return {
                "type": Variant("s", "separator"),
                "visible": Variant("b", True),
            }

        def _children(self):
            # av：每个子项都是 Variant，里面装一个 (ia{sv}av) 结构
            out = []
            for item_id, _title, _action in MENU_ITEMS:
                out.append(Variant("(ia{sv}av)", [item_id, self._props(item_id), []]))
            return out

        @method()
        def GetLayout(self, parent_id: "i", recursion_depth: "i", property_names: "as") -> "u(ia{sv}av)":
            layout = [0, {"children-display": Variant("s", "submenu")}, self._children()]
            return [self._revision, layout]

        @method()
        def GetGroupProperties(self, ids: "ai", property_names: "as") -> "a(ia{sv})":
            wanted = ids or [i for i, _, _ in MENU_ITEMS]
            return [[item_id, self._props(item_id)] for item_id in wanted]

        @method()
        def GetProperty(self, item_id: "i", name: "s") -> "v":
            return self._props(item_id).get(name, Variant("s", ""))

        @method()
        def Event(self, item_id: "i", event_id: "s", data: "v", timestamp: "u"):
            if event_id != "clicked":
                return
            for menu_id, _title, action in MENU_ITEMS:
                if menu_id == item_id and action:
                    self._on_action(action)
                    return

        @method()
        def EventGroup(self, events: "a(isvu)") -> "ai":
            failed = []
            for item_id, event_id, _data, _ts in events:
                if event_id == "clicked":
                    self.Event(item_id, event_id, Variant("s", ""), 0)
            return failed

        @method()
        def AboutToShow(self, item_id: "i") -> "b":
            return False

        @method()
        def AboutToShowGroup(self, ids: "ai") -> "aiai":
            return [[], []]

        @signal()
        def LayoutUpdated(self) -> "ui":
            return [self._revision, 0]

        @signal()
        def ItemsPropertiesUpdated(self) -> "a(ia{sv})a(ias)":
            return [[], []]

        @dbus_property(access=PropertyAccess.READ)
        def Version(self) -> "u":
            return 3

        @dbus_property(access=PropertyAccess.READ)
        def TextDirection(self) -> "s":
            return "ltr"

        @dbus_property(access=PropertyAccess.READ)
        def Status(self) -> "s":
            return "normal"


class SniTray:
    """在后台线程里跑一个 SNI 托盘项。"""

    def __init__(self, title="输入框中译英", pixmaps=None, callbacks=None):
        self.title = title
        self.pixmaps = pixmaps or []
        self.callbacks = callbacks or {}
        self.ready = False
        self.error = None
        self._thread = None
        self._loop = None
        self._bus = None
        self._stopping = False
        self._started = threading.Event()

    # ---- 生命周期 ----
    def start(self, timeout=3.0):
        if not DBUS_AVAILABLE:
            self.error = f"缺少 dbus-next：{DBUS_IMPORT_ERROR}"
            return False
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        self._started.wait(timeout)
        return self.ready

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._bootstrap())
            if self.ready:
                self._loop.run_forever()
        except Exception as error:
            self.error = str(error)
            self.ready = False
        finally:
            self._started.set()
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass

    async def _bootstrap(self):
        try:
            self._bus = await MessageBus().connect()
        except Exception as error:
            self.error = f"无法连接会话总线：{error}"
            return
        name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._bus.export(
            ITEM_PATH,
            StatusNotifierItem("input-translator", self.title, self.pixmaps, self.callbacks),
        )
        self._bus.export(MENU_PATH, DBusMenu(self._on_action))
        try:
            await self._bus.request_name(name)
        except Exception as error:
            self.error = f"无法占用托盘服务名：{error}"
            return
        # 通知托盘宿主（dde-dock / plasmashell / AppIndicator 扩展）
        try:
            introspection = await self._bus.introspect(WATCHER_BUS, WATCHER_PATH)
            proxy = self._bus.get_proxy_object(WATCHER_BUS, WATCHER_PATH, introspection)
            iface = proxy.get_interface(WATCHER_IFACE)
            await iface.call_register_status_notifier_item(name)
        except Exception as error:
            self.error = f"没有可用的系统托盘宿主：{error}"
            return
        self.ready = True
        self._started.set()

    def _on_action(self, action):
        callback = self.callbacks.get(action)
        if callback:
            callback()

    def stop(self):
        if self._loop is None or self._bus is None or self._stopping:
            return
        self._stopping = True

        def _shutdown():
            async def _disconnect():
                try:
                    await self._bus.disconnect()
                except Exception:
                    pass
                self._loop.stop()

            asyncio.ensure_future(_disconnect())

        try:
            self._loop.call_soon_threadsafe(_shutdown)
        except Exception:
            pass
