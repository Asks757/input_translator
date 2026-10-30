import hashlib
import json
import math
import os
import queue
import re
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import font as tkfont
from tkinter import ttk

from pynput import keyboard
from pynput.keyboard import Key
from pynput.mouse import Button as MouseButton
from pynput.mouse import Controller as MouseController
from windowing import (
    IS_WINDOWS,
    activate_window,
    active_window,
    apply_rounded_window_shape,
    enable_dpi_awareness,
    force_focus_window,
    pystray_is_embedded,
)

# 托盘图标：pystray / Pillow 属于可选依赖，缺失时程序照常运行，只是不能收进托盘。
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont

    TRAY_IMPORT_ERROR = None
except Exception as error:  # pragma: no cover - 取决于运行环境
    pystray = None
    Image = ImageDraw = ImageFont = None
    TRAY_IMPORT_ERROR = str(error)

if not IS_WINDOWS:
    try:
        import tray as tray_module
    except Exception:  # pragma: no cover
        tray_module = None
else:
    tray_module = None


APP_FONT = "Microsoft YaHei UI" if IS_WINDOWS else "Noto Sans CJK SC"

# ---- 天蓝配色 ----
SKY_700 = "#0369A1"
SKY_600 = "#0284C7"
SKY_500 = "#0EA5E9"
SKY_300 = "#7DD3FC"
SKY_100 = "#E0F2FE"
SKY_50 = "#F2F9FE"
BORDER = "#D8E8F5"
FIELD_BG = "#F7FBFF"

SETTINGS_BG = "#F3F9FE"
CARD_BG = "#FFFFFF"
TEXT_PRIMARY = "#0F1F33"
TEXT_MUTED = "#64748B"
ACCENT = SKY_600
ACCENT_HOVER = SKY_700

# ---- 悬浮窗：纯黑底 + 白字，仅点缀天蓝 ----
OVERLAY_BG = "#0A0A0A"
OVERLAY_INPUT = "#141414"
OVERLAY_BORDER = "#27333F"
OVERLAY_MUTED = "#9AA7B8"
OVERLAY_ACCENT = "#7DD3FC"
RADIUS_CARD = 18
RADIUS_BUTTON = 12
RADIUS_FIELD = 10
RADIUS_OVERLAY = 20

DEFAULT_HOTKEY = "<ctrl>+<shift>+f"
CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
TARGET_LANGUAGE = "English"
SYSTEM_PROMPT = (
    "Translate all Chinese text in the user's message into natural, fluent English. "
    "Return the complete transformed text only. Preserve existing English, numbers, "
    "URLs, code, whitespace, and line breaks. Do not add explanations, notes, quotes, "
    "or Markdown formatting."
)

# kind = "chat" ：OpenAI 兼容对话模型，用 system prompt 约束输出。
# kind = "mt"   ：OpenAI 兼容专用翻译模型，语种走 translation_options。
# kind = "baidu"：百度通用文本翻译，使用 APP ID + 密钥签名。
PROVIDERS = {
    "baidu": {
        "label": "百度通用文本翻译（高级版每月 100 万字符免费）",
        "base_url": "https://fanyi-api.baidu.com/api/trans/vip/translate",
        "model": "通用文本翻译 · 中译英",
        "kind": "baidu",
        "console": "fanyi-api.baidu.com",
    },
    "zhipu": {
        "label": "智谱 GLM-4.7-Flash（永久免费，国内直连）",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.7-flash",
        "kind": "chat",
        "console": "open.bigmodel.cn",
    },
    "siliconflow": {
        "label": "硅基流动 Qwen2.5-7B（免费额度，国内直连）",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "kind": "chat",
        "console": "cloud.siliconflow.cn",
    },
    "dashscope-mt": {
        "label": "阿里百炼 Qwen-MT（专用翻译模型，按量计费）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-mt-turbo",
        "kind": "mt",
        "console": "bailian.console.aliyun.com",
    },
    "dashscope": {
        "label": "阿里百炼 Qwen-Plus（免费额度，通用对话）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "kind": "chat",
        "console": "bailian.console.aliyun.com",
    },
    "moonshot": {
        "label": "Kimi / Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k3.1-pro",
        "kind": "chat",
        "console": "platform.moonshot.cn",
    },
    "deepseek": {
        "label": "DeepSeek（便宜，质量高）",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "kind": "chat",
        "console": "platform.deepseek.com",
    },
}
DEFAULT_PROVIDER = "zhipu"
PROVIDER_BY_LABEL = {value["label"]: key for key, value in PROVIDERS.items()}

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".translator_config.json"
)


def rounded_rectangle_points(x1, y1, x2, y2, radius, steps=10):
    points = []
    corners = (
        (x2 - radius, y1 + radius, -90),
        (x2 - radius, y2 - radius, 0),
        (x1 + radius, y2 - radius, 90),
        (x1 + radius, y1 + radius, 180),
    )
    for center_x, center_y, start_angle in corners:
        for step in range(steps + 1):
            angle = math.radians(start_angle + step * 90 / steps)
            points.extend(
                (
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle),
                )
            )
    return points


ROUNDED_FRAMES = []


class RoundedFrame(tk.Canvas):
    """画一个圆角底板，内容放在内含的 Frame 里。

    stretch=True 时随父容器拉伸（用于填满剩余空间的输入区）；
    否则高度由内容撑开（用于卡片、输入框外壳）。
    """

    def __init__(
        self,
        master,
        radius=RADIUS_CARD,
        fill=CARD_BG,
        outline="",
        padding=0,
        bg=None,
        stretch=False,
        border_width=1,
    ):
        container_bg = bg or master["bg"]
        super().__init__(
            master, bg=container_bg, highlightthickness=0, borderwidth=0, bd=0
        )
        self.radius = radius
        self.fill = fill
        self.outline = outline or fill
        self.padding = padding
        self.border_width = border_width
        self.stretch = stretch
        self.body = tk.Frame(self, bg=fill)
        self._window = self.create_window(
            padding, padding, anchor="nw", window=self.body
        )
        self.bind("<Configure>", self._on_configure)
        ROUNDED_FRAMES.append(self)

    def refresh(self):
        """布局稳定后再校正一次尺寸（早期 Configure 时子控件往往还没量好）。"""
        width = self.winfo_width()
        if width < 4:
            return
        inner = max(1, width - 2 * self.padding)
        self.itemconfigure(self._window, width=inner)
        self.update_idletasks()
        if self.stretch:
            height = self.winfo_height()
            self.itemconfigure(self._window, width=inner, height=max(1, height - 2 * self.padding))
            self._draw(width, height)
            return
        wanted = self.body.winfo_reqheight() + 2 * self.padding
        try:
            current = int(float(self["height"]))
        except (TypeError, ValueError):
            current = -1
        if abs(current - wanted) > 1:
            self.configure(height=wanted)
        self._draw(width, max(wanted, 4))

    def _on_configure(self, event):
        # 统一由容器自身的尺寸变化驱动：先画底板，再决定内容区尺寸。
        if event.width < 4 or event.height < 4:
            return
        width, height = event.width, event.height
        self._draw(width, height)
        inner_width = max(1, width - 2 * self.padding)
        if self.stretch:
            self.itemconfigure(
                self._window,
                width=inner_width,
                height=max(1, height - 2 * self.padding),
            )
            return
        # 非拉伸模式：宽度撑满父容器，高度由内容决定。
        self.itemconfigure(self._window, width=inner_width)
        wanted = self.body.winfo_reqheight() + 2 * self.padding
        try:
            current = int(float(self["height"]))
        except (TypeError, ValueError):
            current = -1
        if abs(current - wanted) > 1:
            self.configure(height=wanted)

    def _draw(self, width, height):
        self.delete("bgshape")
        points = rounded_rectangle_points(
            1, 1, width - 2, height - 2, min(self.radius, min(width, height) / 2)
        )
        self.create_polygon(
            points,
            fill=self.fill,
            outline=self.outline,
            width=self.border_width,
            tags="bgshape",
        )
        self.tag_lower("bgshape")


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        master,
        text,
        command=None,
        fill=ACCENT,
        hover=ACCENT_HOVER,
        fg="#FFFFFF",
        container_bg=None,
        radius=RADIUS_BUTTON,
        pad_x=22,
        pad_y=10,
        font=None,
        outline="",
    ):
        font = font or (APP_FONT, 10, "bold")
        probe = tkfont.Font(font=font)
        width = probe.measure(text) + 2 * pad_x
        height = probe.metrics("linespace") + 2 * pad_y
        super().__init__(
            master,
            width=width,
            height=height,
            bg=container_bg or master["bg"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.command = command
        self._fill = fill
        self._hover = hover
        self._fg = fg
        self._font = font
        self._text = text
        self._outline = outline or fill
        points = rounded_rectangle_points(1, 1, width - 2, height - 2, radius)
        self._shape = self.create_polygon(
            points, fill=fill, outline=self._outline
        )
        self.create_text(
            width / 2, height / 2, text=text, fill=fg, font=font
        )
        self.bind("<Enter>", lambda _e: self.itemconfigure(self._shape, fill=hover))
        self.bind("<Leave>", lambda _e: self.itemconfigure(self._shape, fill=fill))
        self.bind("<ButtonRelease-1>", self._on_click)

    def _on_click(self, _event=None):
        self.itemconfigure(self._shape, fill=self._fill)
        if self.command:
            self.command()


class Pill(tk.Canvas):
    """胶囊形标签，用于标题右侧的小徽标。"""

    def __init__(
        self,
        master,
        text,
        fill=SKY_100,
        fg=SKY_700,
        container_bg=None,
        font=None,
        pad_x=12,
        pad_y=5,
    ):
        font = font or (APP_FONT, 9)
        probe = tkfont.Font(font=font)
        width = probe.measure(text) + 2 * pad_x
        height = probe.metrics("linespace") + 2 * pad_y
        super().__init__(
            master,
            width=width,
            height=height,
            bg=container_bg or master["bg"],
            highlightthickness=0,
            bd=0,
        )
        points = rounded_rectangle_points(1, 1, width - 2, height - 2, height / 2)
        self.create_polygon(points, fill=fill, outline=fill)
        self.create_text(width / 2, height / 2, text=text, fill=fg, font=font)


class CheckRow(tk.Frame):
    """自绘勾选：选中是圆角方块里的白色对勾，未选中是空心圆角框。"""

    def __init__(
        self,
        master,
        text,
        variable,
        command=None,
        bg=CARD_BG,
        fg=TEXT_MUTED,
        font=None,
    ):
        super().__init__(master, bg=bg)
        self.variable = variable
        self.command = command
        self._bg = bg
        self.box = tk.Canvas(
            self, width=20, height=20, bg=bg, highlightthickness=0, bd=0, cursor="hand2"
        )
        self.box.pack(side="left")
        self.label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=font or (APP_FONT, 9),
            cursor="hand2",
        )
        self.label.pack(side="left", padx=(8, 0))
        for widget in (self.box, self.label):
            widget.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self):
        self.box.delete("all")
        checked = bool(self.variable.get())
        points = rounded_rectangle_points(1.5, 1.5, 18.5, 18.5, 6)
        self.box.create_polygon(
            points,
            fill=ACCENT if checked else CARD_BG,
            outline=ACCENT if checked else "#C3D3E0",
            width=1.4,
        )
        if checked:
            self.box.create_line(
                5.5,
                10.2,
                8.6,
                13.4,
                14.8,
                6.6,
                fill="#FFFFFF",
                width=2.2,
                capstyle="round",
                joinstyle="round",
            )

    def refresh(self):
        self._draw()

    def _toggle(self, _event=None):
        self.variable.set(not bool(self.variable.get()))
        self._draw()
        if self.command:
            self.command()


def hotkey_label(hotkey):
    text = hotkey
    for token, name in (
        ("<ctrl>", "Ctrl"),
        ("<shift>", "Shift"),
        ("<alt>", "Alt"),
        ("<cmd>", "Super"),
    ):
        text = text.replace(token, name)
    return "+".join(part.upper() if len(part) == 1 else part for part in text.split("+"))


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_config(data):
    """把配置写到项目目录，权限 600（仅当前用户可读）。"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.chmod(CONFIG_PATH, 0o600)
    except OSError as error:
        return False, f"保存失败：{error}"
    return True, CONFIG_PATH


def remove_config():
    try:
        os.remove(CONFIG_PATH)
    except FileNotFoundError:
        pass
    except OSError as error:
        return False, f"删除失败：{error}"
    return True, None


def contains_chinese(text):
    return CHINESE_RE.search(text) is not None


def translation_endpoint(base_url):
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    return endpoint


def build_payload(text, model, kind):
    if kind == "mt":
        # Qwen-MT 这类专用翻译模型：只接受一条 user message，语种走 translation_options。
        return {
            "model": model,
            "messages": [{"role": "user", "content": text}],
            "translation_options": {
                "source_lang": "Chinese",
                "target_lang": TARGET_LANGUAGE,
            },
        }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }


def translate_baidu(text, app_id, api_key, base_url, timeout=20):
    if not app_id:
        raise RuntimeError("百度翻译需要 APP ID，请到设置窗口填写。")
    salt = str(time.time_ns())
    signature = hashlib.md5(f"{app_id}{text}{salt}{api_key}".encode("utf-8")).hexdigest()
    form = {
        "q": text,
        "from": "zh",
        "to": "en",
        "appid": app_id,
        "salt": salt,
        "sign": signature,
    }
    request = urllib.request.Request(
        base_url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "input-translator/0.3",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"百度翻译返回 HTTP {error.code}，请稍后重试。") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接百度翻译：{error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("百度翻译返回了无法解析的响应") from error

    if "error_code" in result:
        code = result["error_code"]
        detail = result.get("error_msg", "未知错误")
        hints = {
            "52003": "请检查 APP ID 是否正确、服务是否已开通。",
            "54001": "请检查 APP ID 和密钥是否匹配。",
            "54003": "请求过于频繁，请稍后再试。",
            "54004": "免费额度或账户余额不足，请到百度控制台检查。",
            "90107": "个人认证未通过或尚未生效，请检查认证状态。",
        }
        hint = hints.get(str(code), "请到百度翻译控制台检查服务和额度。")
        raise RuntimeError(f"百度翻译错误 {code}：{detail}。{hint}")
    try:
        translated = "\n".join(
            item["dst"] for item in result["trans_result"] if item.get("dst")
        )
    except (KeyError, TypeError) as error:
        raise RuntimeError("百度翻译响应中没有翻译结果") from error
    if not translated.strip():
        raise RuntimeError("百度翻译返回了空的翻译结果")
    return translated.strip()


def translate_text(
    text, api_key, model, base_url, kind="chat", timeout=60, retries=2, app_id=""
):
    if kind == "baidu":
        return translate_baidu(text, app_id, api_key, base_url)
    payload = build_payload(text, model, kind)
    endpoint = translation_endpoint(base_url)

    for attempt in range(retries + 1):
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "input-translator/0.3",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body).get("error", {}).get("message", body)
            except json.JSONDecodeError:
                detail = body
            last_error = RuntimeError(f"翻译 API 返回 HTTP {error.code}：{detail[:500]}")
            # 免费额度常见 429 限速，稍等重试一次通常就能过。
            if error.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_error from error
        except urllib.error.URLError as error:
            last_error = RuntimeError(f"无法连接翻译 API：{error.reason}")
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_error from error
        except json.JSONDecodeError as error:
            raise RuntimeError("翻译 API 返回了无法解析的响应") from error

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("翻译 API 响应中没有翻译结果") from error
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("翻译 API 返回了空的翻译结果")
    return content.strip()


def build_tray_image(size=64):
    """画托盘图标：天蓝圆角底 + 白色「译」。没有 Pillow 时返回 None。"""
    if Image is None:
        return None
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, size // 16)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=int(size * 0.26),
        fill=SKY_600,
    )
    glyph = "译"
    font = None
    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if not os.path.exists(candidate):
            continue
        try:
            font = ImageFont.truetype(candidate, int(size * 0.6))
            break
        except Exception:
            font = None
    if font is None:
        # 没有可用字体就画一道白色横杠，至少不是空图标
        draw.rectangle(
            (int(size * 0.3), int(size * 0.44), int(size * 0.7), int(size * 0.56)),
            fill="#FFFFFF",
        )
        return image
    left, top, right, bottom = draw.textbbox((0, 0), glyph, font=font)
    draw.text(
        ((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
        glyph,
        font=font,
        fill="#FFFFFF",
    )
    return image


class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.overlay_visible = False
        self.target_window = None
        self.original_clipboard = None

        config = load_config()
        provider_key = (
            os.environ.get("TRANSLATOR_PROVIDER")
            or config.get("provider")
            or DEFAULT_PROVIDER
        )
        if provider_key not in PROVIDERS:
            provider_key = DEFAULT_PROVIDER
        self.provider = provider_key
        saved_here = config.get("provider") == provider_key
        self.model = (
            os.environ.get("TRANSLATOR_MODEL")
            or (config.get("model") if saved_here else None)
            or PROVIDERS[provider_key]["model"]
        )
        self.base_url = (
            os.environ.get("TRANSLATOR_BASE_URL")
            or (config.get("base_url") if saved_here else None)
            or PROVIDERS[provider_key]["base_url"]
        )
        # 环境变量属于临时覆盖，不应该被写进本地配置
        self._env_fields = {
            name
            for name, env in (("model", "TRANSLATOR_MODEL"), ("base_url", "TRANSLATOR_BASE_URL"))
            if os.environ.get(env)
        }
        self.hotkey = os.environ.get("TRANSLATOR_HOTKEY", DEFAULT_HOTKEY)
        self.keyboard = keyboard.Controller()
        self.mouse = MouseController()

        saved_key = config.get("api_key")
        if not isinstance(saved_key, str):
            saved_key = ""
        self.api_key = tk.StringVar(
            value=os.environ.get("TRANSLATOR_API_KEY", "")
            or os.environ.get("MOONSHOT_API_KEY", "")
            or saved_key
        )
        saved_app_id = config.get("app_id") if saved_here else ""
        if not isinstance(saved_app_id, str):
            saved_app_id = ""
        self.app_id = tk.StringVar(
            value=os.environ.get("TRANSLATOR_BAIDU_APP_ID", "") or saved_app_id
        )
        self.remember = tk.BooleanVar(value=bool(saved_key))
        try:
            saved_opacity = float(config.get("opacity", 0.9))
        except (TypeError, ValueError):
            saved_opacity = 0.9
        self.opacity = tk.DoubleVar(value=min(1.0, max(0.3, saved_opacity)))

        self.provider_var = tk.StringVar(value=PROVIDERS[provider_key]["label"])
        self.status = tk.StringVar(value="正在启动全局快捷键……")

        root.title("输入框中译英")
        root.geometry("640x600")
        root.minsize(600, 580)
        root.configure(bg=SETTINGS_BG)
        self._configure_styles()
        self._build_settings_ui()
        self._build_overlay()

        self.listener = keyboard.GlobalHotKeys({self.hotkey: self._on_hotkey})
        self.listener.start()
        # 兜底：无边框窗口偶尔会丢掉键盘焦点，Esc 便传不到 Tk，
        # 这里用全局按键监听补一个「悬浮窗开着时按 Esc 就关」的通道。
        self.esc_listener = None
        try:
            self.esc_listener = keyboard.Listener(on_press=self._on_global_key)
            self.esc_listener.start()
        except Exception:
            self.esc_listener = None
        # 托盘：把窗口收起来时不占任务栏，右键托盘图标可以再打开或退出。
        self.tray = None
        self.tray_kind = None
        self.tray_ready = False

        if saved_key:
            self.status.set(f"已加载本地保存的 Key。按 {self.hotkey_text} 呼出悬浮窗。")
        else:
            self.status.set(f"填入 Key 后，按 {self.hotkey_text} 呼出悬浮窗。")
        # 放在状态提示之后：托盘不可用时要用更重要的提示覆盖上面这句。
        self._setup_tray()
        root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        root.after(100, self._poll_events)
        self._layout_after = None
        root.bind("<Configure>", self._on_root_configure)
        root.after(80, self._settle_layout)
        if os.environ.get("TRANSLATOR_START_HIDDEN") == "1" and self.tray_ready:
            self.root.after(200, self._minimize_to_tray)

    # ---------------- 托盘 ----------------

    def _tray_callbacks(self):
        """托盘线程只往队列里塞事件，不直接碰 Tk。"""
        return {
            "overlay": lambda: self.events.put(("tray", "overlay")),
            "settings": lambda: self.events.put(("tray", "settings")),
            "quit": lambda: self.events.put(("tray", "quit")),
            "menu": lambda x, y: self.events.put(("tray", ("menu", x, y))),
        }

    def _setup_tray(self):
        self.tray = None
        self.tray_kind = None
        self.tray_ready = False
        image = build_tray_image(48)
        if image is None:
            self.status.set("未安装 Pillow，无法生成托盘图标。")
            return

        # Linux 首选 StatusNotifierItem；Windows 直接使用下方的 pystray 原生托盘。
        if tray_module is not None and tray_module.DBUS_AVAILABLE:
            pixmaps = []
            for size in (22, 24, 32, 48):
                scaled = image.resize((size, size))
                pixmaps.append((size, size, tray_module.rgba_to_argb(scaled)))
            sni = tray_module.SniTray(
                title="输入框中译英",
                pixmaps=pixmaps,
                callbacks=self._tray_callbacks(),
            )
            if sni.start():
                self.tray = sni
                self.tray_kind = "sni"
                self.tray_ready = True
                return
            tray_error = sni.error
        else:
            tray_error = (
                tray_module.DBUS_IMPORT_ERROR
                if tray_module
                else ("Windows 托盘初始化失败" if IS_WINDOWS else "未安装 dbus-next")
            )

        # dde-dock 只认 SNI，回退到 XEmbed 会得到一个看不见的图标，反而更危险。
        desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
        if "deepin" in desktop or "dde" in desktop:
            self.status.set(f"托盘注册失败（{tray_error}），关闭窗口将直接退出。")
            return

        # Windows 原生托盘；Linux 上作为 Xfce 等桌面的 XEmbed 回退。
        if pystray is not None:
            menu = pystray.Menu(
                pystray.MenuItem(
                    "呼出悬浮窗",
                    lambda _icon=None, _item=None: self.events.put(("tray", "overlay")),
                    default=True,
                ),
                pystray.MenuItem(
                    "显示设置窗口",
                    lambda _icon=None, _item=None: self.events.put(("tray", "settings")),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "退出",
                    lambda _icon=None, _item=None: self.events.put(("tray", "quit")),
                ),
            )
            try:
                self.tray = pystray.Icon("input-translator", image, "输入框中译英", menu)
                threading.Thread(target=self._run_tray, daemon=True).start()
                if not self._pystray_embedded(self.tray):
                    # 图标没被托盘宿主接管 = 用户根本看不到，不能就这样把窗口藏起来
                    self.tray.stop()
                    self.tray = None
                    self.status.set(
                        f"系统托盘不可用（{tray_error}），关闭窗口将直接退出。"
                    )
                    return
                self.tray_kind = "pystray"
                self.tray_ready = True
                return
            except Exception:
                self.tray = None
        self.status.set(f"当前桌面没有可用的系统托盘（{tray_error}），关闭窗口将直接退出。")

    def _pystray_embedded(self, icon, timeout=1.0):
        return pystray_is_embedded(icon, timeout)

    def _run_tray(self):
        try:
            self.tray.run()
        except Exception:
            self.tray_ready = False

    def _on_window_close(self):
        """点窗口的 ×：能收进托盘就收，不能就正常退出。"""
        if self.tray_ready:
            self._minimize_to_tray()
        else:
            self.close()

    def _minimize_to_tray(self):
        if not self.tray_ready:
            self.status.set("当前桌面没有可用的系统托盘，无法收进托盘。")
            return
        if self.overlay_visible:
            self._hide_overlay()
        self.root.withdraw()

    def _restore_from_tray(self, overlay=False):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            return
        self.status.set(f"监听中：{self.hotkey_text}。")
        if overlay:
            self.root.after(60, self._show_overlay)

    def _tray_menu_popup(self, x, y):
        """给直接调用 ContextMenu 的宿主兜一个 Tk 菜单。"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="呼出悬浮窗", command=self._show_overlay)
        menu.add_command(label="显示设置窗口", command=self._restore_from_tray)
        menu.add_separator()
        menu.add_command(label="退出", command=self.close)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_root_configure(self, event):
        if event.widget is not self.root:
            return
        if self._layout_after is not None:
            self.root.after_cancel(self._layout_after)
        self._layout_after = self.root.after(80, self._settle_layout)

    def _settle_layout(self, attempt=0):
        self._layout_after = None
        for frame in list(ROUNDED_FRAMES):
            try:
                frame.refresh()
            except tk.TclError:
                pass
        if attempt < 2:
            self.root.after(60, self._settle_layout, attempt + 1)

    @property
    def hotkey_text(self):
        return hotkey_label(self.hotkey)

    # ---------------- 设置窗口 ----------------

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "App.TCombobox",
            fieldbackground=FIELD_BG,
            background=FIELD_BG,
            foreground=TEXT_PRIMARY,
            bordercolor=FIELD_BG,
            lightcolor=FIELD_BG,
            darkcolor=FIELD_BG,
            arrowcolor=ACCENT,
            arrowsize=14,
            borderwidth=0,
            relief="flat",
            padding=7,
            font=(APP_FONT, 10),
        )
        style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", FIELD_BG)],
            selectbackground=[("readonly", FIELD_BG)],
            selectforeground=[("readonly", TEXT_PRIMARY)],
        )

    def _build_settings_ui(self):
        frame = tk.Frame(self.root, bg=SETTINGS_BG, padx=26, pady=22)
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg=SETTINGS_BG)
        header.pack(fill="x")
        tk.Label(
            header,
            text="输入框中译英",
            bg=SETTINGS_BG,
            fg=TEXT_PRIMARY,
            font=(APP_FONT, 20, "bold"),
        ).pack(side="left")

        tk.Label(
            frame,
            text="在任意输入框前呼出悬浮窗，让中文自然变成英文。",
            bg=SETTINGS_BG,
            fg=TEXT_MUTED,
            font=(APP_FONT, 10),
        ).pack(anchor="w", pady=(8, 16))

        card = RoundedFrame(
            frame,
            radius=RADIUS_CARD,
            fill=CARD_BG,
            outline=BORDER,
            padding=20,
            bg=SETTINGS_BG,
        )
        card.pack(fill="x")
        body = card.body

        def field_label(text):
            label = tk.Label(
                body,
                text=text,
                bg=CARD_BG,
                fg=TEXT_PRIMARY,
                font=(APP_FONT, 10, "bold"),
            )
            label.pack(anchor="w")
            return label

        field_label("翻译服务")
        combo_shell = RoundedFrame(
            body,
            radius=RADIUS_FIELD,
            fill=FIELD_BG,
            outline=BORDER,
            padding=3,
            bg=CARD_BG,
        )
        combo_shell.pack(fill="x", pady=(8, 16))
        provider_box = ttk.Combobox(
            combo_shell.body,
            textvariable=self.provider_var,
            values=[value["label"] for value in PROVIDERS.values()],
            state="readonly",
            style="App.TCombobox",
        )
        provider_box.pack(fill="x")
        provider_box.bind("<<ComboboxSelected>>", self._on_provider_change)

        self.app_id_label = field_label("APP ID")
        self.app_id_shell = RoundedFrame(
            body,
            radius=RADIUS_FIELD,
            fill=FIELD_BG,
            outline=BORDER,
            padding=4,
            bg=CARD_BG,
        )
        self.app_id_shell.pack(fill="x", pady=(8, 16))
        tk.Entry(
            self.app_id_shell.body,
            textvariable=self.app_id,
            bg=FIELD_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=(APP_FONT, 11),
        ).pack(fill="x", ipady=6, padx=4)

        self.api_key_label = field_label("API Key")
        entry_shell = RoundedFrame(
            body,
            radius=RADIUS_FIELD,
            fill=FIELD_BG,
            outline=BORDER,
            padding=4,
            bg=CARD_BG,
        )
        entry_shell.pack(fill="x", pady=(8, 10))
        tk.Entry(
            entry_shell.body,
            textvariable=self.api_key,
            show="•",
            bg=FIELD_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=(APP_FONT, 11),
        ).pack(fill="x", ipady=6, padx=4)

        self.remember_check = CheckRow(
            body,
            text="记住 Key（仅保存在本机，明文存储）",
            variable=self.remember,
            command=self._on_remember_toggle,
            bg=CARD_BG,
            fg=TEXT_MUTED,
        )
        self.remember_check.pack(anchor="w")

        model_box = RoundedFrame(
            body,
            radius=12,
            fill=SKY_50,
            outline=SKY_100,
            padding=12,
            bg=CARD_BG,
        )
        model_box.pack(fill="x", pady=(14, 0))
        self.model_label = tk.Label(
            model_box.body,
            text=self._model_text(),
            bg=SKY_50,
            fg=TEXT_MUTED,
            wraplength=460,
            justify="left",
            font=(APP_FONT, 9),
        )
        self.model_label.pack(anchor="w")
        model_box.body.bind(
            "<Configure>",
            lambda event: self.model_label.configure(
                wraplength=max(120, event.width - 4)
            ),
        )
        self._update_credential_fields()

        hints = tk.Frame(frame, bg=SETTINGS_BG)
        hints.pack(fill="x", pady=(16, 8))
        for text, primary in (
            (f"{self.hotkey_text}  呼出 / 收起", True),
            ("Ctrl+Enter  翻译并填入", False),
            ("Esc  关闭", False),
        ):
            Pill(
                hints,
                text,
                fill=SKY_100 if primary else "#EAF3FA",
                fg=SKY_700 if primary else "#5B7488",
                container_bg=SETTINGS_BG,
                pad_x=10,
                pad_y=4,
            ).pack(side="left", padx=(0, 8))

        tk.Label(
            frame,
            textvariable=self.status,
            bg=SETTINGS_BG,
            fg=SKY_700,
            wraplength=560,
            justify="left",
            font=(APP_FONT, 9),
        ).pack(anchor="w")

        buttons = tk.Frame(frame, bg=SETTINGS_BG)
        buttons.pack(fill="x", side="bottom", pady=(14, 0))
        RoundedButton(
            buttons,
            "呼出悬浮窗",
            command=self._show_overlay,
            fill=ACCENT,
            hover=ACCENT_HOVER,
            fg="#FFFFFF",
            container_bg=SETTINGS_BG,
            pad_x=22,
            pad_y=11,
        ).pack(side="left")
        RoundedButton(
            buttons,
            "退出",
            command=self.close,
            fill=CARD_BG,
            hover="#E9F4FC",
            fg=TEXT_MUTED,
            container_bg=SETTINGS_BG,
            outline=BORDER,
            pad_x=24,
            pad_y=11,
            font=(APP_FONT, 10),
        ).pack(side="right")
        RoundedButton(
            buttons,
            "收进托盘",
            command=self._minimize_to_tray,
            fill=CARD_BG,
            hover="#E9F4FC",
            fg=SKY_700,
            container_bg=SETTINGS_BG,
            outline=BORDER,
            pad_x=18,
            pad_y=11,
            font=(APP_FONT, 10),
        ).pack(side="right", padx=(0, 10))

    def _update_credential_fields(self):
        is_baidu = self.provider == "baidu"
        self.api_key_label.config(text="密钥" if is_baidu else "API Key")
        if is_baidu:
            self.app_id_label.pack(before=self.api_key_label, anchor="w")
            self.app_id_shell.pack(
                before=self.api_key_label, fill="x", pady=(8, 16)
            )
            self.root.minsize(600, 660)
            if self.root.winfo_height() < 680:
                width = self.root.winfo_width()
                self.root.geometry(f"{width if width > 100 else 640}x680")
        else:
            self.app_id_label.pack_forget()
            self.app_id_shell.pack_forget()
            self.root.minsize(600, 580)

    def _model_text(self):
        if self.provider == "baidu":
            return (
                f"服务：{self.model}　接口：{self.base_url}"
                f"（APP ID 和密钥在 {PROVIDERS[self.provider]['console']} 获取）"
            )
        return (
            f"模型：{self.model}　接口：{self.base_url}"
            f"（Key 在 {PROVIDERS[self.provider]['console']} 申请）"
        )

    # ---------------- 悬浮窗 ----------------

    def _build_overlay(self):
        overlay = tk.Toplevel(self.root)
        overlay.withdraw()
        self.frameless = os.environ.get("TRANSLATOR_FRAMELESS", "1") != "0"
        if self.frameless:
            # 无边框窗口若拿不到键盘焦点，可用 TRANSLATOR_FRAMELESS=0 降级。
            overlay.overrideredirect(True)
        try:
            overlay.attributes("-topmost", True)
            overlay.attributes("-alpha", float(self.opacity.get()))
        except tk.TclError:
            pass
        overlay.configure(bg="#000000")
        self.overlay = overlay
        self.overlay_shape_after = None

        self.overlay_canvas = tk.Canvas(
            overlay, bg="#000000", highlightthickness=0, borderwidth=0
        )
        self.overlay_canvas.pack(fill="both", expand=True)
        panel = tk.Frame(self.overlay_canvas, bg=OVERLAY_BG)
        self.overlay_panel = panel
        self.overlay_panel_window = self.overlay_canvas.create_window(
            2, 2, anchor="nw", window=panel
        )

        header = tk.Frame(panel, bg=OVERLAY_BG, padx=18, pady=14)
        header.pack(fill="x")
        tk.Label(
            header,
            text="●",
            bg=OVERLAY_BG,
            fg=OVERLAY_ACCENT,
            font=(APP_FONT, 10),
        ).pack(side="left")
        tk.Label(
            header,
            text="中译英",
            bg=OVERLAY_BG,
            fg="#FFFFFF",
            font=(APP_FONT, 12, "bold"),
        ).pack(side="left", padx=(7, 0))
        RoundedButton(
            header,
            "×",
            command=self._hide_overlay,
            fill="#1A1A1A",
            hover="#2A2A2A",
            fg=OVERLAY_MUTED,
            container_bg=OVERLAY_BG,
            radius=9,
            pad_x=9,
            pad_y=2,
            font=(APP_FONT, 12),
        ).pack(side="right")
        RoundedButton(
            header,
            "设置",
            command=lambda: self.root.after(0, self._restore_from_tray),
            fill="#1A1A1A",
            hover="#2A2A2A",
            fg=OVERLAY_MUTED,
            container_bg=OVERLAY_BG,
            radius=9,
            pad_x=10,
            pad_y=3,
            font=(APP_FONT, 9),
        ).pack(side="right", padx=(0, 6))
        tk.Label(
            header,
            text=f"{self.hotkey_text} 收起",
            bg=OVERLAY_BG,
            fg=OVERLAY_MUTED,
            font=(APP_FONT, 9),
        ).pack(side="right", padx=(0, 12))

        text_shell = RoundedFrame(
            panel,
            radius=12,
            fill=OVERLAY_INPUT,
            outline=OVERLAY_BORDER,
            padding=1,
            bg=OVERLAY_BG,
            stretch=True,
        )
        text_shell.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.text = tk.Text(
            text_shell.body,
            height=5,
            bg=OVERLAY_INPUT,
            fg="#FFFFFF",
            insertbackground=OVERLAY_ACCENT,
            selectbackground=SKY_700,
            selectforeground="#FFFFFF",
            relief="flat",
            wrap="word",
            font=(APP_FONT, 13),
            padx=12,
            pady=10,
            highlightthickness=0,
            spacing1=2,
            spacing3=2,
        )
        self.text.pack(fill="both", expand=True)
        self.text.bind("<Control-Return>", self._on_overlay_submit)
        self.text.bind("<Control-KP_Enter>", self._on_overlay_submit)
        # Esc 在窗口级绑定（见下方 overlay.bind），任何子控件有焦点都能关。

        self.overlay_status = tk.StringVar(value=self._overlay_hint())
        tk.Label(
            panel,
            textvariable=self.overlay_status,
            bg=OVERLAY_BG,
            fg="#8FA3B8",
            anchor="w",
            font=(APP_FONT, 9),
        ).pack(fill="x", padx=20, pady=(0, 6))

        bar = tk.Frame(panel, bg=OVERLAY_BG, padx=18, pady=12)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="透明度",
            bg=OVERLAY_BG,
            fg=OVERLAY_MUTED,
            font=(APP_FONT, 9),
        ).pack(side="left")
        scale = tk.Scale(
            bar,
            from_=0.3,
            to=1.0,
            resolution=0.05,
            orient="horizontal",
            variable=self.opacity,
            command=self._on_opacity_change,
            bg=OVERLAY_BG,
            fg="#DDE6EF",
            troughcolor="#1F2A35",
            activebackground=SKY_500,
            highlightthickness=0,
            borderwidth=0,
            sliderrelief="flat",
            showvalue=False,
            length=120,
        )
        scale.pack(side="left", padx=(8, 5))
        scale.bind("<ButtonRelease-1>", lambda _event: self._save_opacity())
        self.opacity_value = tk.StringVar()
        tk.Label(
            bar,
            textvariable=self.opacity_value,
            bg=OVERLAY_BG,
            fg=OVERLAY_MUTED,
            width=4,
            font=(APP_FONT, 9),
        ).pack(side="left")
        RoundedButton(
            bar,
            "翻译并填入  Ctrl+Enter",
            command=self._on_overlay_submit,
            fill=SKY_600,
            hover=SKY_700,
            fg="#FFFFFF",
            container_bg=OVERLAY_BG,
            radius=11,
            pad_x=16,
            pad_y=8,
        ).pack(side="right")

        # 点击后重新抢回焦点，避免回填后悬浮窗无法继续输入。
        overlay.bind("<Button-1>", self._refocus_overlay)
        self.overlay_canvas.bind("<Button-1>", self._refocus_overlay)
        self.text.bind("<Button-1>", self._refocus_overlay)

        overlay.bind("<Configure>", self._on_overlay_configure)
        # Esc 关闭：绑在 Toplevel 上，焦点落在输入框、滑块、画布上都能响应。
        overlay.bind("<Escape>", self._on_overlay_escape)
        self.overlay_canvas.bind("<Escape>", self._on_overlay_escape)
        self._on_opacity_change(self.opacity.get())

    def _on_overlay_escape(self, _event=None):
        if self.overlay_visible:
            self._hide_overlay()
        return "break"

    def _on_overlay_configure(self, event):
        if event.widget is not self.overlay or event.width < 50 or event.height < 50:
            return
        self.overlay_canvas.delete("card")
        self.overlay_canvas.create_polygon(
            rounded_rectangle_points(
                1, 1, event.width - 2, event.height - 2, RADIUS_OVERLAY
            ),
            fill=OVERLAY_BG,
            outline=OVERLAY_BORDER,
            width=1,
            tags="card",
        )
        self.overlay_canvas.coords(self.overlay_panel_window, 2, 2)
        self.overlay_canvas.itemconfigure(
            self.overlay_panel_window, width=event.width - 4, height=event.height - 4
        )
        self.overlay_canvas.tag_lower("card")
        if not self.frameless:
            return
        if self.overlay_shape_after is not None:
            self.root.after_cancel(self.overlay_shape_after)
        self.overlay_shape_after = self.root.after(40, self._update_overlay_shape)

    def _update_overlay_shape(self):
        self.overlay_shape_after = None
        apply_rounded_window_shape(
            self.overlay.winfo_id(),
            self.overlay.winfo_width(),
            self.overlay.winfo_height(),
            radius=RADIUS_OVERLAY,
        )

    def _overlay_hint(self):
        return "输入中文，Ctrl+Enter 翻译并填入原输入框　·　Esc 关闭"

    def _show_overlay(self):
        if self.busy:
            self.status.set("上一次翻译还没完成，请稍候。")
            return
        if not self.overlay_visible:
            try:
                self.target_window = active_window()
            except OSError:
                self.target_window = None
            # 每次呼出都从空白开始，不残留上一轮的原文或译文。
            self._clear_overlay_input()
        overlay = self.overlay
        width = 660
        x = max(0, (overlay.winfo_screenwidth() - width) // 2)
        y = max(0, int(overlay.winfo_screenheight() * 0.18))
        overlay.geometry(f"{width}x360+{x}+{y}")
        try:
            overlay.attributes("-alpha", float(self.opacity.get()))
        except tk.TclError:
            pass
        overlay.deiconify()
        overlay.update_idletasks()
        # 底部工具栏不能被裁掉：窗口高度按内容实际需要兜底。
        needed = self.overlay_panel.winfo_reqheight() + 4
        if needed > overlay.winfo_height():
            overlay.geometry(f"{width}x{needed}+{x}+{y}")
        overlay.lift()
        overlay.focus_force()
        self.text.focus_force()
        self.overlay_visible = True
        self.overlay_status.set(self._overlay_hint())
        # 刚 map 出来的窗口 WM 还不会给焦点，稍等一下再强制抢一次。
        self.root.after(60, self._refocus_overlay)
        self.root.after(160, self._prime_overlay_focus)
        self._start_focus_ticker()

    def _clear_overlay_input(self):
        """清空输入区：每次呼出悬浮窗都应该是干净的。"""
        try:
            self.text.delete("1.0", "end")
            # Ctrl+Z 不能把上一轮的内容撤回来
            self.text.edit_reset()
            self.text.mark_set("insert", "1.0")
            self.text.see("1.0")
        except tk.TclError:
            pass
        try:
            self.overlay_status.set(self._overlay_hint())
        except tk.TclError:
            pass

    def _prime_overlay_focus(self):
        """无边框窗口光设焦点不够：真实点一下输入区，Tk 的输入法上下文才会收键。"""
        if not self.overlay_visible:
            return
        try:
            self.mouse.position = (
                self.overlay.winfo_rootx() + 40,
                self.overlay.winfo_rooty() + 64,
            )
            time.sleep(0.05)
            self.mouse.click(MouseButton.left, 1)
            self.text.focus_force()
        except Exception:
            pass

    def _start_focus_ticker(self):
        self._stop_focus_ticker()
        self._focus_ticker = self.root.after(250, self._keep_overlay_focus)

    def _stop_focus_ticker(self):
        ticker = getattr(self, "_focus_ticker", None)
        if ticker is not None:
            try:
                self.root.after_cancel(ticker)
            except tk.TclError:
                pass
            self._focus_ticker = None

    def _keep_overlay_focus(self):
        """无边框窗口会被窗管器判为"非活动"并清掉焦点，这里持续把焦点按回去。"""
        self._focus_ticker = None
        if not self.overlay_visible:
            return
        try:
            if self.overlay.focus_get() is not self.text:
                self.text.focus_force()
        except tk.TclError:
            pass
        self._focus_ticker = self.root.after(250, self._keep_overlay_focus)

    def _refocus_overlay(self, _event=None):
        try:
            force_focus_window(str(self.overlay.winfo_id()))
            self.overlay.focus_force()
            self.text.focus_force()
        except tk.TclError:
            pass

    def _hide_overlay(self):
        self._stop_focus_ticker()
        self.overlay.withdraw()
        self.overlay_visible = False
        self._save_opacity()
        self.status.set(f"悬浮窗已关闭。按 {self.hotkey_text} 再次呼出。")

    def _on_opacity_change(self, value):
        try:
            numeric_value = float(value)
            self.overlay.attributes("-alpha", numeric_value)
            self.opacity_value.set(f"{round(numeric_value * 100)}%")
        except (tk.TclError, ValueError):
            pass

    # ---------------- 翻译流程 ----------------

    def _on_hotkey(self):
        self.events.put(("hotkey", None))

    def _toggle_overlay(self):
        if self.overlay_visible:
            self._hide_overlay()
        else:
            self._show_overlay()

    def _on_overlay_submit(self, _event=None):
        if self.busy:
            self.overlay_status.set("上一次翻译还没完成，请稍候。")
            return "break"
        text = self.text.get("1.0", "end").strip()
        if not text:
            self.overlay_status.set("先输入要翻译的中文。")
            return "break"
        if not contains_chinese(text):
            self.overlay_status.set("没有检测到中文，无需翻译。")
            return "break"
        api_key = self.api_key.get().strip()
        app_id = self.app_id.get().strip()
        if self.provider == "baidu" and not app_id:
            self.overlay_status.set("还没填百度 APP ID，请到设置窗口填写。")
            self.root.deiconify()
            self.root.lift()
            return "break"
        if not api_key:
            credential = "百度密钥" if self.provider == "baidu" else "API Key"
            self.overlay_status.set(f"还没填{credential}，请到设置窗口填写。")
            self.root.deiconify()
            self.root.lift()
            return "break"

        self.busy = True
        self.original_clipboard = self._get_clipboard()
        self.overlay_status.set(f"正在用 {self.model} 翻译……")
        self._persist_if_wanted()
        threading.Thread(
            target=self._translate_worker, args=(text, api_key, app_id), daemon=True
        ).start()
        return "break"

    def _translate_worker(self, text, api_key, app_id):
        try:
            translated = translate_text(
                text,
                api_key,
                self.model,
                self.base_url,
                kind=PROVIDERS[self.provider]["kind"],
                app_id=app_id,
            )
            self.events.put(("success", translated))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _on_global_key(self, key):
        """全局兜底：只在悬浮窗可见时把 Esc 转成关闭请求。"""
        try:
            if key == Key.esc and self.overlay_visible:
                self.events.put(("escape", None))
        except Exception:
            pass

    def _poll_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "hotkey":
                    self._toggle_overlay()
                elif event == "escape":
                    # Tk 自己已经处理过的话，这里看到的就是已关闭状态，直接忽略。
                    if self.overlay_visible:
                        self._hide_overlay()
                elif event == "tray":
                    if isinstance(payload, tuple) and payload[0] == "menu":
                        self._tray_menu_popup(payload[1], payload[2])
                        continue
                    if payload == "quit":
                        self.close()
                        return
                    if payload == "overlay":
                        # 只弹悬浮窗，设置窗口继续保持收起状态（不占任务栏）。
                        self._show_overlay()
                    elif payload == "settings":
                        self._restore_from_tray()
                elif event == "success":
                    self._deliver(payload)
                elif event == "error":
                    self._fail(payload)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._poll_events)

    def _deliver(self, translated):
        self.busy = False
        if not self.target_window:
            self._set_clipboard(translated)
            self.overlay_status.set("没找到目标窗口，译文已复制到剪贴板，手动粘贴即可。")
            return
        self.overlay_status.set("正在填入原输入框……")
        if not activate_window(self.target_window):
            self._set_clipboard(translated)
            self.overlay_status.set("无法激活原输入框，译文已复制到剪贴板，手动粘贴即可。")
            return
        self.root.after(200, self._paste_translated, translated)

    def _paste_translated(self, translated):
        try:
            self._release_modifiers()
            self._set_clipboard(translated)
            self._press_ctrl("v")
        except (OSError, tk.TclError) as error:
            self.overlay_status.set(f"粘贴失败：{error}")
            return
        self._clear_overlay_input()
        self.root.after(600, self._restore_clipboard)
        self.overlay_status.set("已填入原输入框，悬浮窗已清空。")

    def _fail(self, message):
        self.busy = False
        self.overlay_status.set(f"翻译失败：{message}")
        self.status.set(f"翻译失败：{message}")
        if self.original_clipboard is not None:
            self._restore_clipboard()

    # ---------------- 配置持久化 ----------------

    def _current_config(self):
        preset = PROVIDERS[self.provider]
        data = {
            "provider": self.provider,
            "model": preset["model"] if "model" in self._env_fields else self.model,
            "base_url": preset["base_url"]
            if "base_url" in self._env_fields
            else self.base_url,
            "opacity": round(float(self.opacity.get()), 2),
        }
        api_key = self.api_key.get().strip()
        if self.remember.get() and api_key:
            data["api_key"] = api_key
            if self.provider == "baidu" and self.app_id.get().strip():
                data["app_id"] = self.app_id.get().strip()
        return data

    def _persist_if_wanted(self):
        if not self.remember.get():
            return True, None
        if not self.api_key.get().strip():
            return True, None
        return write_config(self._current_config())

    def _save_opacity(self):
        if self.remember.get() and self.api_key.get().strip():
            write_config(self._current_config())

    def _on_provider_change(self, _event=None):
        key = PROVIDER_BY_LABEL.get(self.provider_var.get())
        if not key or key == self.provider:
            return
        self.provider = key
        self.model = PROVIDERS[key]["model"]
        self.base_url = PROVIDERS[key]["base_url"]
        self._update_credential_fields()
        self.model_label.config(text=self._model_text())
        credential = "APP ID 和密钥" if key == "baidu" else "API Key"
        self.status.set(f"已切换到 {PROVIDERS[key]['label']}，请确认{credential}属于该平台。")
        self._persist_if_wanted()

    def _on_remember_toggle(self):
        if self.remember.get():
            ok, detail = self._persist_if_wanted()
            if not ok:
                self.remember.set(False)
                self.remember_check.refresh()
                self.status.set(f"保存失败：{detail}")
            elif self.api_key.get().strip():
                self.status.set(f"Key 已保存到 {CONFIG_PATH}（权限 600，仅本机可读）。")
            else:
                self.status.set("已开启记忆：填入 Key 后会自动保存到项目本地。")
            return
        ok, detail = remove_config()
        if ok:
            self.status.set("已关闭记忆，并删除本地保存的 Key。")
        else:
            self.status.set(detail)

    # ---------------- 剪贴板 / 按键 ----------------

    def _get_clipboard(self):
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return None

    def _set_clipboard(self, text):
        self.root.clipboard_clear()
        if text is not None:
            self.root.clipboard_append(text)
        self.root.update()

    def _restore_clipboard(self):
        if self.original_clipboard is None:
            return
        try:
            self._set_clipboard(self.original_clipboard)
        except tk.TclError:
            pass

    def _release_modifiers(self):
        """Ctrl+Enter 的修饰键可能还按着，先松开再发 Ctrl+V，避免组合成别的快捷键。"""
        for key in (Key.ctrl, Key.ctrl_r, Key.shift, Key.shift_r, Key.alt, Key.alt_r, Key.enter):
            try:
                self.keyboard.release(key)
            except (KeyError, ValueError):
                pass

    def _press_ctrl(self, character):
        with self.keyboard.pressed(Key.ctrl):
            self.keyboard.press(character)
            self.keyboard.release(character)

    def close(self):
        self._persist_if_wanted()
        try:
            self.listener.stop()
        except Exception:
            pass
        try:
            if self.esc_listener is not None:
                self.esc_listener.stop()
        except Exception:
            pass
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
            self.tray = None
        self.root.destroy()


if __name__ == "__main__":
    if not IS_WINDOWS and os.environ.get("XDG_SESSION_TYPE", "x11").lower() != "x11":
        raise SystemExit("Linux 当前仅支持 X11 桌面。")
    enable_dpi_awareness()
    root = tk.Tk()
    TranslatorApp(root)
    root.mainloop()
