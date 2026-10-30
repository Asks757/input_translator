import os
import shutil
import subprocess
import time

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    user32.SetProcessDPIAware.argtypes = []
    user32.SetProcessDPIAware.restype = wintypes.BOOL
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL
else:
    from Xlib import X, display, protocol
    from Xlib.ext import shape as xshape


def exclude_window_from_capture(window_id):
    if not IS_WINDOWS:
        return False
    try:
        hwnd = user32.GetAncestor(int(window_id), 2) or int(window_id)
        return bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _open_clipboard():
    for _ in range(5):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.05)
    return False


def get_clipboard_text():
    if not IS_WINDOWS or not _open_clipboard():
        return None
    try:
        if not user32.IsClipboardFormatAvailable(13):
            return None
        handle = user32.GetClipboardData(13)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    if not IS_WINDOWS:
        raise OSError("当前平台不支持原生剪贴板接口")
    if not _open_clipboard():
        raise OSError("无法打开剪贴板")
    handle = None
    try:
        if not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        if text is not None:
            data = str(text).encode("utf-16le") + b"\0\0"
            handle = kernel32.GlobalAlloc(0x2000, len(data))
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(pointer, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(13, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = None
    finally:
        if handle:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


def enable_dpi_awareness():
    if IS_WINDOWS:
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def apply_rounded_window_shape(window_id, width, height, radius):
    if IS_WINDOWS:
        region = gdi32.CreateRoundRectRgn(
            0, 0, int(width) + 1, int(height) + 1, int(radius) * 2, int(radius) * 2
        )
        if not region:
            return False
        if user32.SetWindowRgn(int(window_id), region, True):
            return True
        gdi32.DeleteObject(region)
        return False

    x_display = display.Display()
    pixmap = None
    try:
        pixmap = x_display.screen().root.create_pixmap(width, height, 1)
        graphics = pixmap.create_gc(foreground=0)
        pixmap.fill_rectangle(graphics, 0, 0, width, height)
        graphics.change(foreground=1)
        pixmap.fill_rectangle(graphics, radius, 0, width - 2 * radius, height)
        pixmap.fill_rectangle(graphics, 0, radius, width, height - 2 * radius)
        for x, y, angle in (
            (0, 0, 90),
            (width - 2 * radius, 0, 0),
            (width - 2 * radius, height - 2 * radius, -90),
            (0, height - 2 * radius, 180),
        ):
            pixmap.fill_arc(
                graphics, x, y, 2 * radius, 2 * radius, angle * 64, 90 * 64
            )
        window = x_display.create_resource_object("window", int(window_id))
        window.mask(xshape.SO.Set, xshape.SK.Bounding, 0, 0, pixmap)
        x_display.sync()
        return True
    except Exception:
        return False
    finally:
        if pixmap is not None:
            pixmap.free()
        x_display.close()


def active_window():
    if IS_WINDOWS:
        window_id = user32.GetForegroundWindow()
        if not window_id:
            raise OSError("无法读取当前活动窗口")
        return str(window_id)

    x_display = display.Display()
    try:
        atom = x_display.intern_atom("_NET_ACTIVE_WINDOW")
        property_value = x_display.screen().root.get_full_property(atom, X.AnyPropertyType)
        if property_value is None or not property_value.value:
            raise OSError("无法读取当前活动窗口")
        return str(property_value.value[0])
    finally:
        x_display.close()


def activate_window(window_id):
    if not window_id:
        return False
    if IS_WINDOWS:
        try:
            hwnd = int(window_id)
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)
            return bool(user32.SetForegroundWindow(hwnd))
        except (TypeError, ValueError, OSError):
            return False

    if shutil.which("xdotool"):
        try:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", str(window_id)],
                check=True,
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        x_display = display.Display()
    except Exception:
        return False
    try:
        window = x_display.create_resource_object("window", int(window_id))
        atom = x_display.intern_atom("_NET_ACTIVE_WINDOW")
        event = protocol.event.ClientMessage(
            window=window,
            client_type=atom,
            data=(32, [2, X.CurrentTime, 0, 0, 0]),
        )
        x_display.screen().root.send_event(
            event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask
        )
        x_display.sync()
        return True
    except Exception:
        return False
    finally:
        x_display.close()


def window_has_focus(window_id):
    if IS_WINDOWS:
        try:
            return int(user32.GetForegroundWindow()) == int(window_id)
        except (TypeError, ValueError):
            return False

    try:
        x_display = display.Display()
    except Exception:
        return True
    try:
        focus = x_display.get_input_focus().focus
        current = getattr(focus, "id", None)
        target = int(window_id)
        for _ in range(4):
            if current is None:
                return False
            if int(current) == target:
                return True
            parent = x_display.create_resource_object("window", int(current)).query_tree().parent
            current = getattr(parent, "id", None)
            if current == x_display.screen().root.id:
                return False
        return False
    except Exception:
        return True
    finally:
        x_display.close()


def force_focus_window(window_id):
    if not window_id:
        return False
    if IS_WINDOWS:
        return activate_window(window_id)

    if shutil.which("xdotool"):
        try:
            subprocess.run(
                ["xdotool", "windowfocus", "--sync", str(window_id)],
                check=True,
                timeout=3,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        x_display = display.Display()
    except Exception:
        return False
    try:
        window = x_display.create_resource_object("window", int(window_id))
        x_display.set_input_focus(window, X.RevertToParent, X.CurrentTime)
        x_display.sync()
        return True
    except Exception:
        return False
    finally:
        x_display.close()


def pystray_is_embedded(icon, timeout=1.0):
    if IS_WINDOWS:
        return True
    window = getattr(icon, "_window", None)
    if window is None:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            x_display = display.Display()
            try:
                parent = x_display.create_resource_object(
                    "window", window.id
                ).query_tree().parent
                if parent.id != x_display.screen().root.id:
                    return True
            finally:
                x_display.close()
        except Exception:
            return True
        time.sleep(0.2)
    return False
