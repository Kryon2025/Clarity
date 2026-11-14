"""桌面图标显示/隐藏（浅清 / 覆清 专注期间隐藏桌面图标）。

实现方式：找到桌面的 SHELLDLL_DefView 窗口，用 ShowWindow 隐藏/显示；
不改注册表、不改系统设置，退出或恢复时立即还原，进程异常退出后下次启动自动还原。
"""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

SW_HIDE = 0
SW_SHOW = 5

_hidden_by_us = False


def _find_desktop_view() -> int:
    if sys.platform != "win32":
        return 0
    user32 = ctypes.windll.user32
    progman = user32.FindWindowW("Progman", None)
    if progman:
        view = user32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
        if view:
            return int(view)
        # 某些系统桌面在 WorkerW 下
        worker = user32.FindWindowExW(0, 0, "WorkerW", None)
        while worker:
            view = user32.FindWindowExW(worker, 0, "SHELLDLL_DefView", None)
            if view:
                return int(view)
            worker = user32.FindWindowExW(0, worker, "WorkerW", None)
    return 0


def desktop_icons_visible() -> bool:
    view = _find_desktop_view()
    if not view or sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.user32.IsWindowVisible(view))
    except Exception:  # noqa: BLE001
        return True


def hide_desktop_icons() -> bool:
    """隐藏桌面图标；成功返回 True。"""
    global _hidden_by_us
    view = _find_desktop_view()
    if not view:
        return False
    try:
        ctypes.windll.user32.ShowWindow(view, SW_HIDE)
        _hidden_by_us = True
        logger.info("已隐藏桌面图标")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("隐藏桌面图标失败：%s", exc)
        return False


def show_desktop_icons() -> bool:
    """恢复桌面图标；成功返回 True。"""
    global _hidden_by_us
    view = _find_desktop_view()
    if not view:
        return False
    try:
        ctypes.windll.user32.ShowWindow(view, SW_SHOW)
        _hidden_by_us = False
        logger.info("已恢复桌面图标")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("恢复桌面图标失败：%s", exc)
        return False


def hidden_by_us() -> bool:
    return _hidden_by_us
