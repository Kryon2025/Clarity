"""邮件发送（stdlib smtplib + email.message）。

配置全部来自环境变量（见 config.Settings / .env.example）：

- SMTP_HOST、SMTP_PORT（默认 587）、SMTP_USER、SMTP_PASSWORD、SMTP_FROM
- SMTP_TLS（默认 1）、SMTP_SSL（默认 0）
- MAIL_DEV_MODE（默认 0）

没有配置 SMTP 或 MAIL_DEV_MODE=1 时**不连服务器**：把验证码写进日志，
由调用方把 dev_code 放进响应，方便本地/联调环境（正式部署不会返回 dev_code）。
发送失败抛 MailError，其 str() 就是可直接给用户看的中文提示，绝不冒泡成 500。
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

try:  # 作为包导入
    from .config import Settings
except ImportError:  # 在 server/ 目录内直接运行
    from config import Settings  # type: ignore

__all__ = [
    "MailConfig",
    "MailError",
    "PURPOSE_LABELS",
    "SMTP_TIMEOUT_SECONDS",
    "build_message",
    "config_from_settings",
    "is_dev_mode",
    "send_code",
]

logger = logging.getLogger("shenqing.mailer")

#: SMTP 超时（秒）：连接/读写都不能卡住请求线程
SMTP_TIMEOUT_SECONDS = 10
#: 发件人显示名
SENDER_NAME = "深清商店"

PURPOSE_LABELS = {
    "register": "注册",
    "login": "登录",
    "reset": "重置密码",
}

SUBJECTS = {
    "register": "深清商店 · 注册验证码",
    "login": "深清商店 · 登录验证码",
    "reset": "深清商店 · 重置密码验证码",
}


class MailError(RuntimeError):
    """发送失败；str(exc) 是可直接展示的中文提示。"""


@dataclass(frozen=True)
class MailConfig:
    """SMTP 配置（不可变，测试直接构造）。"""

    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""
    tls: bool = True
    ssl: bool = False
    dev_mode: bool = False

    @property
    def configured(self) -> bool:
        """有服务器地址 + 发件地址才算配好。"""
        return bool(self.host and (self.sender or self.user))

    @property
    def from_address(self) -> str:
        return self.sender or self.user


def config_from_settings(settings: Settings) -> MailConfig:
    return MailConfig(
        host=str(getattr(settings, "smtp_host", "") or "").strip(),
        port=int(getattr(settings, "smtp_port", 587) or 587),
        user=str(getattr(settings, "smtp_user", "") or "").strip(),
        password=str(getattr(settings, "smtp_password", "") or ""),
        sender=str(getattr(settings, "smtp_from", "") or "").strip(),
        tls=bool(getattr(settings, "smtp_tls", True)),
        ssl=bool(getattr(settings, "smtp_ssl", False)),
        dev_mode=bool(getattr(settings, "mail_dev_mode", False)),
    )


def is_dev_mode(config: MailConfig) -> bool:
    """开发模式：显式开启，或压根没配置 SMTP。"""
    return bool(config.dev_mode) or not config.configured


def _body(code: str, purpose: str, ttl_seconds: int) -> str:
    label = PURPOSE_LABELS.get(purpose, "验证")
    minutes = max(1, int(round(ttl_seconds / 60)))
    return (
        "你好：\n"
        "\n"
        "你正在进行「" + label + "」操作，验证码是：\n"
        "\n"
        "    " + code + "\n"
        "\n"
        "该验证码 " + str(minutes) + " 分钟内有效，且仅可使用一次，请勿转发给任何人。\n"
        "如果这不是你本人的操作，忽略这封邮件即可。\n"
        "\n"
        "—— 深清商店\n"
    )


def build_message(
    config: MailConfig, email: str, purpose: str, code: str, ttl_seconds: int
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = SUBJECTS.get(purpose, "深清商店验证码")
    message["From"] = formataddr((SENDER_NAME, config.from_address))
    message["To"] = email
    message["Date"] = formatdate(localtime=False)
    domain = config.from_address.rpartition("@")[2] or "shenqing.local"
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(_body(code, purpose, ttl_seconds), subtype="plain", charset="utf-8")
    return message


def _deliver(config: MailConfig, message: EmailMessage) -> None:
    """真正连 SMTP 发信；所有异常都翻译成中文 MailError。"""
    server = None
    try:
        if config.ssl:
            server = smtplib.SMTP_SSL(
                config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS
            )
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=SMTP_TIMEOUT_SECONDS)
        server.ehlo()
        if config.tls and not config.ssl:
            server.starttls()
            server.ehlo()
        if config.user:
            server.login(config.user, config.password)
        server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("邮件发送失败：SMTP 账号认证未通过，请检查 SMTP_USER / SMTP_PASSWORD") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError("邮件发送失败：收件地址被邮件服务器拒绝，请检查邮箱是否正确") from exc
    except smtplib.SMTPException as exc:
        raise MailError("邮件发送失败：SMTP 服务器返回错误（" + str(exc) + "）") from exc
    except (OSError, TimeoutError) as exc:
        raise MailError("邮件发送失败：无法连接邮件服务器，请稍后重试") from exc
    finally:
        if server is not None:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass


def send_code(
    config: MailConfig,
    email: str,
    purpose: str,
    code: str,
    ttl_seconds: int,
) -> bool:
    """发送验证码邮件。

    - 开发模式（未配置 SMTP 或 MAIL_DEV_MODE=1）：不发送，只写日志，返回 False；
    - 正常发送成功：返回 True；
    - 失败：抛 MailError（中文提示）。
    """
    if is_dev_mode(config):
        logger.warning(
            "开发模式未发送邮件：%s 的%s验证码为 %s（%s 秒内有效）",
            email,
            PURPOSE_LABELS.get(purpose, "验证"),
            code,
            ttl_seconds,
        )
        return False
    message = build_message(config, email, purpose, code, ttl_seconds)
    _deliver(config, message)
    logger.info("已发送%s验证码邮件：%s", PURPOSE_LABELS.get(purpose, "验证"), email)
    return True
