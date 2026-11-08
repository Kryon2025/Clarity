"""专注期间全局鼠标左键点击计数（v0.14）。

优先安装 WH_MOUSE_LL 低级鼠标钩子；钩子失败自动降级为每 50ms 轮询
GetAsyncKeyState(VK_LBUTTON) 的边沿检测。只统计 start()~stop() 期间的物理点击。
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger("shenqing.click_counter")

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
VK_LBUTTON = 0x01
POLL_INTERVAL_MS = 50

_WIN = os.name == "nt"
if _WIN:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        _HOOKPROC,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    ]
    _user32.CallNextHookEx.restype = ctypes.c_ssize_t
    _user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]


def is_left_button_down() -> bool:
    if not _WIN:
        return False
    try:
        return bool(int(_user32.GetAsyncKeyState(VK_LBUTTON)) & 0x8000)
    except Exception:  # noqa: BLE001
        return False


class ClickCounter(QObject):
    """统计锁定期间的鼠标左键点击数。"""

    changed = Signal(int)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        button_provider=None,  # noqa: ANN001
        poll_interval_ms: int = POLL_INTERVAL_MS,
    ) -> None:
        super().__init__(parent)
        self._count = 0
        self._active = False
        self._hook = 0
        self._hook_proc = None
        self._fallback = False
        self._last_down = False
        self._button_provider = button_provider or is_left_button_down
        self._timer = QTimer(self)
        self._timer.setInterval(max(10, int(poll_interval_ms)))
        self._timer.timeout.connect(self._poll)

    # ---------- 状态 ----------
    @property
    def count(self) -> int:
        return int(self._count)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def fallback(self) -> bool:
        return self._fallback

    @property
    def hook_installed(self) -> bool:
        return bool(self._hook)

    # ---------- 生命周期 ----------
    def start(self) -> None:
        if self._active:
            return
        self._count = 0
        self._last_down = bool(self._button_provider())
        self._active = True
        self._fallback = not self._install_hook()
        if self._fallback:
            logger.info("鼠标钩子安装失败，降级为 50ms 轮询计数")
            self._timer.start()
        self.changed.emit(self._count)

    def stop(self) -> int:
        """结束统计并返回本轮点击数。"""
        if not self._active:
            return self._count
        self._active = False
        self._timer.stop()
        self._uninstall_hook()
        self._fallback = False
        return self._count

    def reset(self) -> None:
        self._count = 0
        self._last_down = False
        self.changed.emit(self._count)

    # ---------- 钩子 ----------
    def _install_hook(self) -> bool:
        if not _WIN:
            return False
        try:
            self._hook_proc = _HOOKPROC(self._hook_callback)
            hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, None, 0)
            self._hook = int(hook or 0)
            return bool(self._hook)
        except Exception as exc:  # noqa: BLE001
            logger.info("安装鼠标钩子失败：%s", exc)
            self._hook = 0
            self._hook_proc = None
            return False

    def _uninstall_hook(self) -> None:
        if not self._hook:
            self._hook_proc = None
            return
        try:
            _user32.UnhookWindowsHookEx(self._hook)
        except Exception:  # noqa: BLE001
            pass
        self._hook = 0
        self._hook_proc = None

    def _hook_callback(self, code, wparam, lparam):  # noqa: ANN001
        try:
            if code >= 0 and self._active and int(wparam) == WM_LBUTTONDOWN:
                self._register_click()
        except Exception:  # noqa: BLE001
            pass
        try:
            return _user32.CallNextHookEx(self._hook, code, wparam, lparam)
        except Exception:  # noqa: BLE001
            return 0

    # ---------- 轮询降级 ----------
    def _poll(self) -> None:
        if not self._active:
            return
        down = bool(self._button_provider())
        if down and not self._last_down:
            self._register_click()
        self._last_down = down

    # ---------- 计数 ----------
    def _register_click(self) -> None:
        if not self._active:
            return
        self._count += 1
        self.changed.emit(self._count)

    # 供测试直接模拟一次点击
    def simulate_click(self) -> None:
        self._register_click()
