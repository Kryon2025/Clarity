"""清番（v0.16）：置顶番茄钟，与锁机 / guard 完全独立。

- 专注 25 分钟 → 短休息 5 分钟；每 4 轮专注后进入 15 分钟长休息
- 计时使用 time.monotonic()，电脑休眠 / 改系统时间不跑偏
- 到点通过 notify 信号发系统通知（由 bridge 接到 NotificationService）并自动切换阶段
- 只维护自己的番茄状态，不读写专注会话 / 守卫 / 统计，可与任意档位专注同时存在
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Mapping

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger("shenqing.pomodoro")

PHASE_IDLE = "idle"
PHASE_WORK = "work"
PHASE_BREAK = "break"

DEFAULT_WORK_MINUTES = 25
DEFAULT_BREAK_MINUTES = 5
DEFAULT_LONG_BREAK_MINUTES = 15
DEFAULT_ROUNDS_BEFORE_LONG = 4

WORK_KEY = "pomodoro_work_minutes"
BREAK_KEY = "pomodoro_break_minutes"
LONG_BREAK_KEY = "pomodoro_long_break_minutes"
ROUNDS_KEY = "pomodoro_rounds_before_long"


class PomodoroTimer(QObject):
    """番茄钟状态机（idle → work ⇄ break），可随时暂停 / 跳过 / 退出。"""

    changed = Signal()          # 任何状态变化（供 QML 属性通知）
    tick = Signal(int)          # 当前阶段剩余秒数
    notify = Signal(str, str)   # (标题, 正文) 到点提醒
    phaseFinished = Signal(str)  # 刚刚结束的阶段：work / break

    def __init__(
        self,
        settings: Mapping | None = None,
        parent: QObject | None = None,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings if settings is not None else {}
        self._now = now or time.monotonic
        self._running = False
        self._paused = False
        self._phase = PHASE_IDLE
        self._round = 0
        self._preset_total = 0
        self._remaining = 0
        self._long_break = False
        self._last_tick_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timeout)

    # ---------- 配置 ----------
    def _int_setting(self, key: str, default: int, low: int = 1, high: int = 240) -> int:
        raw = None
        try:
            if hasattr(self._settings, "get"):
                raw = self._settings.get(key, default)  # type: ignore[union-attr]
            elif isinstance(self._settings, Mapping):
                raw = self._settings.get(key, default)
        except Exception:  # noqa: BLE001 - 设置读失败用默认值
            raw = None
        try:
            value = int(raw) if raw is not None else int(default)
        except (TypeError, ValueError):
            value = int(default)
        return max(low, min(high, value))

    @property
    def work_minutes(self) -> int:
        return self._int_setting(WORK_KEY, DEFAULT_WORK_MINUTES)

    @property
    def break_minutes(self) -> int:
        return self._int_setting(BREAK_KEY, DEFAULT_BREAK_MINUTES)

    @property
    def long_break_minutes(self) -> int:
        return self._int_setting(LONG_BREAK_KEY, DEFAULT_LONG_BREAK_MINUTES)

    @property
    def rounds_before_long(self) -> int:
        return self._int_setting(ROUNDS_KEY, DEFAULT_ROUNDS_BEFORE_LONG, 1, 20)

    # ---------- 只读状态 ----------
    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def remaining(self) -> int:
        if self._running and not self._paused:
            drift = int(max(0.0, self._now() - self._last_tick_at))
            return max(0, self._remaining - drift)
        return self._remaining

    @property
    def preset_total(self) -> int:
        return self._preset_total

    @property
    def round(self) -> int:
        return self._round

    @property
    def is_long_break(self) -> bool:
        return bool(self._long_break)

    # ---------- 控制 ----------
    def start(self) -> bool:
        """从头开始一轮清番（专注阶段）。已在运行则忽略。"""
        if self._running:
            return False
        self._running = True
        self._paused = False
        self._phase = PHASE_WORK
        self._round = 1
        self._long_break = False
        self._preset_total = self.work_minutes * 60
        self._remaining = self._preset_total
        self._last_tick_at = self._now()
        self._timer.start()
        self.changed.emit()
        self.tick.emit(self._remaining)
        return True

    def pause(self) -> bool:
        if not self._running or self._paused:
            return False
        self._consume_elapsed()
        if self._remaining <= 0:
            self._advance(notify=True)
            return True
        self._timer.stop()
        self._paused = True
        self.changed.emit()
        return True

    def resume(self) -> bool:
        if not self._running or not self._paused:
            return False
        self._paused = False
        self._last_tick_at = self._now()
        self._timer.start()
        self.changed.emit()
        return True

    def stop(self) -> bool:
        """退出清番：清空全部状态，不触发通知。"""
        if not self._running:
            return False
        self._timer.stop()
        self._running = False
        self._paused = False
        self._phase = PHASE_IDLE
        self._round = 0
        self._long_break = False
        self._preset_total = 0
        self._remaining = 0
        self._last_tick_at = 0.0
        self.changed.emit()
        self.tick.emit(0)
        return True

    def skip(self) -> bool:
        """跳过当前阶段，立即进入下一阶段（不通知）。"""
        if not self._running:
            return False
        self._advance(notify=False)
        return True

    # ---------- 内部计时 ----------
    def _consume_elapsed(self) -> int:
        now = self._now()
        elapsed = int(max(0.0, now - self._last_tick_at))
        self._last_tick_at = now
        if elapsed:
            self._remaining = max(0, self._remaining - elapsed)
        return elapsed

    def _advance(self, *, notify: bool) -> None:
        finished = self._phase
        if finished == PHASE_WORK:
            self._long_break = self._round % self.rounds_before_long == 0
            minutes = self.long_break_minutes if self._long_break else self.break_minutes
            self._phase = PHASE_BREAK
        else:
            self._phase = PHASE_WORK
            self._round += 1
            self._long_break = False
            minutes = self.work_minutes
        self._preset_total = max(1, int(minutes)) * 60
        self._remaining = self._preset_total
        self._paused = False
        self._last_tick_at = self._now()
        self._timer.start()
        self.phaseFinished.emit(finished)
        if notify:
            self._emit_notification(finished)
        self.changed.emit()
        self.tick.emit(self._remaining)

    def _emit_notification(self, finished: str) -> None:
        try:
            if finished == PHASE_WORK:
                if self._long_break:
                    title = "清番 · 专注结束"
                    body = f"该长休息了，{self.long_break_minutes} 分钟后再战"
                else:
                    title = "清番 · 专注结束"
                    body = f"休息 {self.break_minutes} 分钟"
            else:
                title = "清番 · 休息结束"
                body = f"开始第 {self._round} 轮专注（{self.work_minutes} 分钟）"
            self.notify.emit(title, body)
        except Exception as exc:  # noqa: BLE001 - 通知失败不能中断番茄钟
            logger.warning("清番通知发送失败：%s", exc)

    def _on_timeout(self) -> None:
        if not self._running or self._paused:
            return
        now = self._now()
        steps = max(1, int(round(max(0.0, now - self._last_tick_at))))
        self._last_tick_at = now
        self._remaining = max(0, self._remaining - steps)
        if self._remaining <= 0:
            self._advance(notify=True)
            return
        self.tick.emit(self._remaining)
        self.changed.emit()
