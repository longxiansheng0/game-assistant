"""抓屏 + 前台窗口识别。

只抓一帧，绝不做常驻循环：游戏运行时 GPU 很宝贵。
"""

from __future__ import annotations

import ctypes
import io
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from PIL import Image

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 64 位下必须声明签名，否则 HWND/HANDLE 会被截断成 c_int，窗口识别直接失效
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


@dataclass
class Capture:
    jpeg: bytes
    title: str
    process: str
    width: int
    height: int
    full: Any = None  # 原始分辨率图，只给 OCR 用，用完即弃

    @property
    def game_name(self) -> str:
        return guess_game_name(self.title, self.process)


def ensure_dpi_aware() -> None:
    """不设 DPI 感知的话，高缩放屏上抓出来的图会错位。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def _window_process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(handle)
    return ""


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def focus_window(hwnd: int) -> None:
    """把焦点还给游戏。我们此刻是前台进程，系统允许。"""
    if hwnd:
        try:
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
        except Exception:
            pass


def foreground_info() -> tuple[str, str]:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value, _window_process_name(hwnd)


def _foreground_rect() -> tuple[int, int, int, int] | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    if rect.right - rect.left < 200 or rect.bottom - rect.top < 200:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _pick_monitor(sct, rect: tuple[int, int, int, int] | None) -> dict:
    monitors = sct.monitors[1:] or [sct.monitors[0]]
    if rect is None:
        return monitors[0]
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    for mon in monitors:
        if (
            mon["left"] <= cx < mon["left"] + mon["width"]
            and mon["top"] <= cy < mon["top"] + mon["height"]
        ):
            return mon
    return monitors[0]


def grab(max_width: int = 1280, quality: int = 82, keep_full: bool = False) -> Capture:
    """抓前台窗口所在的那块屏幕，压成 JPEG。keep_full 时额外留一张原图给 OCR。"""
    import mss

    ensure_dpi_aware()
    title, process = foreground_info()
    with mss.mss() as sct:
        mon = _pick_monitor(sct, _foreground_rect())
        raw = sct.grab(mon)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    full = img.copy() if keep_full else None

    if img.width > max_width:
        height = round(img.height * max_width / img.width)
        img = img.resize((max_width, height), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return Capture(
        jpeg=buf.getvalue(),
        title=title,
        process=process,
        width=img.width,
        height=img.height,
        full=full,
    )


# 常见游戏进程名 -> 中文名。认不出来也没关系，标题里通常带名字。
_PROCESS_ALIASES = {
    "yuanshen.exe": "原神",
    "genshinimpact.exe": "原神",
    "starrail.exe": "崩坏：星穹铁道",
    "zenlesszonezero.exe": "绝区零",
    "bh3.exe": "崩坏3",
    "wutheringwaves.exe": "鸣潮",
    "deltarune.exe": "",
    "eldenring.exe": "艾尔登法环",
    "sekiro.exe": "只狼",
    "bg3.exe": "博德之门3",
    "bg3_dx11.exe": "博德之门3",
    "cyberpunk2077.exe": "赛博朋克2077",
    "witcher3.exe": "巫师3",
    "league of legends.exe": "英雄联盟",
    "dota2.exe": "DOTA2",
    "valorant-win64-shipping.exe": "无畏契约",
    "cs2.exe": "CS2",
    "deltaforce.exe": "三角洲行动",
    "naraka.exe": "永劫无间",
    "palworld-win64-shipping.exe": "幻兽帕鲁",
    "stardew valley.exe": "星露谷物语",
    "terraria.exe": "泰拉瑞亚",
    "minecraft.exe": "我的世界",
    "javaw.exe": "我的世界",
}

_NOISE_SUFFIX = (
    " - Windows",
    " — Mozilla Firefox",
    " - Google Chrome",
    " - Microsoft Edge",
)


def guess_game_name(title: str, process: str) -> str:
    alias = _PROCESS_ALIASES.get((process or "").lower())
    if alias:
        return alias
    clean = title or ""
    for suffix in _NOISE_SUFFIX:
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
    # 很多游戏标题形如 "游戏名 - 版本 1.2.3"
    for sep in (" - ", "—", " | "):
        if sep in clean:
            head = clean.split(sep)[0].strip()
            if head:
                clean = head
                break
    return clean.strip()[:40]
