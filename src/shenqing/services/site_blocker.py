"""专注期间通过 Windows hosts 屏蔽网站（v0.15）。

- 备份原始 hosts 到 %APPDATA%/ShenQing/hosts.backup（仅首次）；
- 写入标记段 # >>> ShenQing block >>> ... # <<< ShenQing block <<<，每域名 0.0.0.0 与 ::1；
- 恢复时删除标记段（hosts 被清空时回退到备份），保留用户其他条目；
- 非管理员直接失败（不写 hosts），提示需要管理员权限；
- 进程崩溃后启动时可清理残留标记段。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..paths import app_data_dir
from ..services.elevation import is_admin as default_is_admin

logger = logging.getLogger("shenqing.site_blocker")

BLOCK_START = "# >>> ShenQing block >>>"
BLOCK_END = "# <<< ShenQing block <<<"
HOSTS_BACKUP_NAME = "hosts.backup"

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"([a-z]{2,63}|xn--[a-z0-9-]{2,59})$"
)


def normalize_domain(value: object) -> str:
    """去协议/路径/端口/首尾点，转小写；非法域名返回空串。"""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        try:
            from urllib.parse import urlsplit

            text = str(urlsplit(text).hostname or "")
        except ValueError:
            return ""
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if ":" in text:
        text = text.rsplit(":", 1)[0]
    text = text.strip(".")
    if not text or len(text) > 253 or "_" in text:
        return ""
    return text if _DOMAIN_RE.match(text) else ""


def normalize_domains(values) -> list[str]:  # noqa: ANN001
    result: list[str] = []
    for item in values or []:
        domain = normalize_domain(item)
        if domain and domain not in result:
            result.append(domain)
    return result


def hosts_path() -> Path:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return Path(root) / "System32" / "drivers" / "etc" / "hosts"


def backup_path() -> Path:
    return app_data_dir() / HOSTS_BACKUP_NAME


class HostsSiteBlocker:
    def __init__(
        self,
        path: Path | None = None,
        backup: Path | None = None,
        admin_checker=None,  # noqa: ANN001
        flush_dns: bool = True,
    ) -> None:
        self._path = Path(path) if path else hosts_path()
        self._backup = Path(backup) if backup else backup_path()
        self._admin_checker = admin_checker or default_is_admin
        self._flush_dns = bool(flush_dns)

    # ---------- 状态 ----------
    @property
    def path(self) -> Path:
        return self._path

    @property
    def backup(self) -> Path:
        return self._backup

    def is_admin(self) -> bool:
        try:
            return bool(self._admin_checker())
        except Exception:  # noqa: BLE001
            return False

    def is_blocked(self) -> bool:
        return BLOCK_START in self._read()

    # ---------- 应用 / 恢复 ----------
    def apply(self, domains) -> tuple[bool, str]:  # noqa: ANN001
        sites = normalize_domains(domains)
        if not sites:
            return self.restore()
        if not self.is_admin():
            return False, "需要管理员权限才能修改 hosts 屏蔽网站"
        try:
            current = self._read()
            self._ensure_backup(current)
            base = self._strip_block(current)
            if base and not base.endswith("\n"):
                base += "\n"
            lines = [BLOCK_START]
            for domain in sites:
                lines.append(f"0.0.0.0 {domain}")
                lines.append(f"::1 {domain}")
            lines.append(BLOCK_END)
            self._write(base + "\n".join(lines) + "\n")
            self._flush_dns_cache()
            logger.info("已屏蔽 %s 个网站", len(sites))
            return True, ""
        except OSError as exc:
            logger.warning("写入 hosts 失败：%s", exc)
            return False, "写入 hosts 失败（需要管理员权限）"

    def restore(self) -> tuple[bool, str]:
        """删除标记段；如果 hosts 只剩标记段则还原首次备份。"""
        if not self._path.exists():
            return True, ""
        if not self.is_blocked():
            # 没有我们的标记段时绝不重写 hosts
            return True, ""
        if not self.is_admin():
            return False, "需要管理员权限才能恢复 hosts"
        try:
            current = self._read()
            stripped = self._strip_block(current)
            if not stripped.strip() and self._backup.exists():
                try:
                    stripped = self._read(self._backup)
                except OSError:
                    stripped = ""
            self._write(stripped)
            self._flush_dns_cache()
            return True, ""
        except OSError as exc:
            logger.warning("恢复 hosts 失败：%s", exc)
            return False, "恢复 hosts 失败（需要管理员权限）"

    def cleanup_stale(self) -> tuple[bool, str]:
        """启动时清理上一次崩溃残留的屏蔽段。"""
        if not self._path.exists():
            return True, ""
        if not self.is_blocked():
            return True, ""
        if not self.is_admin():
            return False, "检测到残留的网站屏蔽，需要管理员权限清理"
        return self.restore()

    # ---------- 内部 ----------
    def _read(self, path: Path | None = None) -> str:
        target = path or self._path
        try:
            return target.read_text(encoding="utf-8", errors="surrogateescape")
        except FileNotFoundError:
            return ""
        except OSError:
            return ""

    def _write(self, text: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_name(self._path.name + ".shenqing.tmp")
        temp.write_text(text, encoding="utf-8", errors="surrogateescape")
        os.replace(temp, self._path)

    def _ensure_backup(self, current: str) -> None:
        if self._backup.exists():
            return
        try:
            self._backup.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists():
                shutil.copy2(self._path, self._backup)
            else:
                self._backup.write_text(current, encoding="utf-8", errors="surrogateescape")
        except OSError as exc:
            logger.warning("备份 hosts 失败：%s", exc)

    @staticmethod
    def _strip_block(text: str) -> str:
        pattern = re.compile(
            re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\s*",
            re.DOTALL,
        )
        return pattern.sub("", text)

    def _flush_dns_cache(self) -> None:
        if not self._flush_dns or os.name != "nt":
            return
        try:
            subprocess.run(
                ["ipconfig", "/flushdns"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
