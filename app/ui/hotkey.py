"""全局热键（Win32 RegisterHotKey）。

比键盘钩子安全：不拦截按键、不需要管理员权限、游戏里也能用。
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_SPECIAL = {
    "CAPSLOCK": 0x14,
    "TAB": 0x09,
    "SPACE": 0x20,
    "INSERT": 0x2D,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "ESC": 0x1B,
}

_MODS = {"CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL, "ALT": MOD_ALT, "SHIFT": MOD_SHIFT, "WIN": MOD_WIN}


def parse_key(name: str) -> int | None:
    key = (name or "").strip().upper()
    if key.startswith("F") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x6F + n
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return ord(key)
    return _SPECIAL.get(key)


def parse_combo(name: str) -> tuple[int, int] | None:
    """"Ctrl+F8" -> (MOD_CONTROL, VK_F8)。"""
    parts = [p for p in (name or "").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    for part in parts[:-1]:
        bit = _MODS.get(part.strip().upper())
        if bit is None:
            return None
        mods |= bit
    vk = parse_key(parts[-1])
    if vk is None:
        return None
    return mods, vk


class HotkeyListener(threading.Thread):
    def __init__(self, combo: str, on_trigger, on_error=None) -> None:
        super().__init__(daemon=True)
        self.combo = combo
        parsed = parse_combo(combo)
        self.mods, self.vk = parsed if parsed else (0, None)
        self.on_trigger = on_trigger
        self.on_error = on_error
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self.ok = False

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        if self.vk is None:
            self.ok = False
            self._ready.set()
            if self.on_error:
                self.on_error(f"不认识这个热键：{self.combo}")
            return

        if not user32.RegisterHotKey(None, 1, self.mods, self.vk):
            self.ok = False
            self._ready.set()
            if self.on_error:
                self.on_error(f"热键 {self.combo} 被占用了，去 config/settings.json 换一个")
            return

        self.ok = True
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.on_trigger()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, 1)

    def wait_ready(self, timeout: float = 2.0) -> bool:
        self._ready.wait(timeout)
        return self.ok

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
