"""验证码发送限流：纯内存滑动窗口（进程重启即重置）。

规则（与产品文档一致）：

- 同一邮箱：60 秒 1 次、1 小时 5 次、1 天 10 次；
- 同一 IP：10 分钟 20 次。

只用于 `/api/auth/send-code`，单进程内存计数足够；多副本部署时每个进程各自
计数，公网防刷仍应叠加 Nginx limit_req。时钟可注入（`clock`），便于测试。

用法：

>>> limiter = SendRateLimiter()
>>> ok, reason, retry_after = limiter.allow("a@b.com", "127.0.0.1")
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Callable

__all__ = [
    "EMAIL_DAILY_LIMIT",
    "EMAIL_DAILY_WINDOW_SECONDS",
    "EMAIL_HOURLY_LIMIT",
    "EMAIL_HOURLY_WINDOW_SECONDS",
    "EMAIL_MIN_INTERVAL_SECONDS",
    "IP_LIMIT",
    "IP_WINDOW_SECONDS",
    "SendRateLimiter",
]

#: 同一邮箱最小发送间隔（秒）
EMAIL_MIN_INTERVAL_SECONDS = 60
#: 同一邮箱 1 小时窗口内最多发送次数
EMAIL_HOURLY_LIMIT = 5
EMAIL_HOURLY_WINDOW_SECONDS = 3600
#: 同一邮箱 1 天窗口内最多发送次数
EMAIL_DAILY_LIMIT = 10
EMAIL_DAILY_WINDOW_SECONDS = 86400
#: 同一 IP 10 分钟内最多发送次数
IP_LIMIT = 20
IP_WINDOW_SECONDS = 600


def _prune(hits: deque, now: float, window_seconds: float) -> None:
    """丢掉窗口外的时间戳（deque 按时间递增，从左弹出即可）。"""
    while hits and now - hits[0] >= window_seconds:
        hits.popleft()


def _retry_after(deadline: float, now: float) -> int:
    return max(1, int(math.ceil(deadline - now)))


class SendRateLimiter:
    """发送验证码的频次限制（线程安全，单进程）。"""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self.clock: Callable[[], float] = clock or time.time
        self._email_hits: dict[str, deque] = {}
        self._ip_hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, email: str, ip: str) -> tuple[bool, str, int]:
        """检查并记账。

        返回 `(是否允许, 拒绝原因中文, 建议重试秒数)`；允许时原因为空串、
        重试秒数为 0，同时把本次请求记进两个窗口。
        """
        email_key = str(email or "").strip().lower() or "-"
        ip_key = str(ip or "").strip() or "-"
        with self._lock:
            now = float(self.clock())
            email_hits = self._email_hits.setdefault(email_key, deque())
            _prune(email_hits, now, EMAIL_DAILY_WINDOW_SECONDS)
            if email_hits:
                wait = EMAIL_MIN_INTERVAL_SECONDS - (now - email_hits[-1])
                if wait > 0:
                    retry = _retry_after(EMAIL_MIN_INTERVAL_SECONDS + email_hits[-1], now)
                    return False, "验证码发送太频繁，请 " + str(retry) + " 秒后再试", retry
            hourly = [ts for ts in email_hits if now - ts < EMAIL_HOURLY_WINDOW_SECONDS]
            if len(hourly) >= EMAIL_HOURLY_LIMIT:
                retry = _retry_after(hourly[0] + EMAIL_HOURLY_WINDOW_SECONDS, now)
                return (
                    False,
                    "该邮箱 1 小时内最多发送 " + str(EMAIL_HOURLY_LIMIT) + " 次验证码，请稍后再试",
                    retry,
                )
            if len(email_hits) >= EMAIL_DAILY_LIMIT:
                retry = _retry_after(email_hits[0] + EMAIL_DAILY_WINDOW_SECONDS, now)
                return (
                    False,
                    "该邮箱今日发送验证码次数已达上限（" + str(EMAIL_DAILY_LIMIT) + " 次），请明天再试",
                    retry,
                )

            ip_hits = self._ip_hits.setdefault(ip_key, deque())
            _prune(ip_hits, now, IP_WINDOW_SECONDS)
            if len(ip_hits) >= IP_LIMIT:
                retry = _retry_after(ip_hits[0] + IP_WINDOW_SECONDS, now)
                return (
                    False,
                    "请求过于频繁，请 " + str(retry) + " 秒后再试",
                    retry,
                )

            email_hits.append(now)
            ip_hits.append(now)
            return True, "", 0

    def reset(self) -> None:
        """清空所有计数（测试用）。"""
        with self._lock:
            self._email_hits.clear()
            self._ip_hits.clear()
