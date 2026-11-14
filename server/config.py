"""深清商店服务端配置。

所有配置都来自环境变量（或 server/.env 文件，stdlib 解析，不依赖 python-dotenv）。
测试可以直接构造 Settings 覆盖任意字段。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: 后端代码目录（server/）
SERVER_DIR = Path(__file__).resolve().parent
#: 默认数据库文件（相对于 server/ 目录）
DEFAULT_DATABASE_PATH = SERVER_DIR / "store.db"
#: 默认静态前端目录
DEFAULT_STATIC_DIR = SERVER_DIR / "static"
#: 默认应用版本（/api/catalog.json 顶层 version 也用它）
DEFAULT_APP_VERSION = "0.19.0"


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def read_dotenv(path: Path) -> dict[str, str]:
    """读取 KEY=VALUE 形式的 .env；忽略空行与 # 注释。"""
    data: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        data[key] = _strip_quotes(value.split(" #", 1)[0])
    return data


def load_dotenv(*paths: Path) -> None:
    """把 .env 内容灌进 os.environ（已存在的环境变量优先，不覆盖）。"""
    for path in paths:
        for key, value in read_dotenv(Path(path)).items():
            os.environ.setdefault(key, value)


def _resolve_path(raw: str, default: Path) -> str:
    text = (raw or "").strip()
    if not text:
        return str(default)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = SERVER_DIR / path
    return str(path.resolve())


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_float(name: str, default: float, minimum: float = 1.0) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def _env_bool(name: str, default: bool) -> bool:
    """1/true/yes/on → True，0/false/no/off → False，其它回退默认值。"""
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


@dataclass(frozen=True)
class Settings:
    """运行时配置（不可变；测试直接构造覆盖）。"""

    secret_key: str = "dev-insecure-change-me"
    admin_email: str = ""
    admin_password: str = ""
    database_path: str = str(DEFAULT_DATABASE_PATH)
    token_ttl_seconds: int = 7 * 24 * 60 * 60
    cors_origins: tuple[str, ...] = ("*",)
    app_version: str = DEFAULT_APP_VERSION
    static_dir: str = str(DEFAULT_STATIC_DIR)
    public_base_url: str = ""
    #: 启动时是否用 ADMIN_EMAIL/ADMIN_PASSWORD 引导管理员
    bootstrap_admin: bool = True
    # ---------------- 邮件验证码（SMTP） ----------------
    #: SMTP 服务器；为空则进入开发模式（不发信，只把验证码写日志）
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    #: 发件地址（默认回退 SMTP_USER）
    smtp_from: str = ""
    #: 587 端口通常要 STARTTLS
    smtp_tls: bool = True
    #: 465 端口用隐式 SSL；与 smtp_tls 互斥
    smtp_ssl: bool = False
    #: 强制开发模式：不发信、响应里带 dev_code（严禁在生产开启）
    mail_dev_mode: bool = False
    #: 验证码有效期（秒）
    email_code_ttl_seconds: int = 600
    #: 单个验证码最多尝试次数
    email_code_max_attempts: int = 5
    # ---------------- GitHub 发布源同步 ----------------
    #: GitHub API Token（可选）：配置后限额从匿名 60 次/小时 提到 5000 次/小时
    github_token: str = ""
    #: 单次 GitHub API 请求超时（秒）
    github_timeout_seconds: float = 6.0
    #: 后台同步周期（秒），默认 6 小时
    github_sync_interval_seconds: int = 6 * 60 * 60
    #: 是否启动后台同步线程（测试/无网环境可关掉，仍可手动 POST /api/admin/sync）
    github_sync_enabled: bool = True
    extra: dict[str, str] = field(default_factory=dict)


def load_settings() -> Settings:
    """从环境变量 / .env 构造 Settings。每次调用都重新读取，便于测试隔离。"""
    load_dotenv(SERVER_DIR / ".env", Path.cwd() / ".env")

    origins_raw = (os.environ.get("CORS_ORIGINS") or "*").strip()
    origins = tuple(part.strip() for part in origins_raw.split(",") if part.strip()) or ("*",)

    return Settings(
        secret_key=(os.environ.get("SECRET_KEY") or "").strip() or "dev-insecure-change-me",
        admin_email=(os.environ.get("ADMIN_EMAIL") or "").strip().lower(),
        admin_password=os.environ.get("ADMIN_PASSWORD") or "",
        database_path=_resolve_path(os.environ.get("DATABASE_PATH", ""), DEFAULT_DATABASE_PATH),
        token_ttl_seconds=_env_int("TOKEN_TTL_SECONDS", 7 * 24 * 60 * 60, minimum=60),
        cors_origins=origins,
        app_version=(os.environ.get("APP_VERSION") or DEFAULT_APP_VERSION).strip(),
        static_dir=_resolve_path(os.environ.get("STATIC_DIR", ""), DEFAULT_STATIC_DIR),
        public_base_url=(os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/"),
        bootstrap_admin=_env_bool("BOOTSTRAP_ADMIN", True),
        smtp_host=(os.environ.get("SMTP_HOST") or "").strip(),
        smtp_port=_env_int("SMTP_PORT", 587, minimum=1),
        smtp_user=(os.environ.get("SMTP_USER") or "").strip(),
        smtp_password=os.environ.get("SMTP_PASSWORD") or "",
        smtp_from=(os.environ.get("SMTP_FROM") or "").strip(),
        smtp_tls=_env_bool("SMTP_TLS", True),
        smtp_ssl=_env_bool("SMTP_SSL", False),
        mail_dev_mode=_env_bool("MAIL_DEV_MODE", False),
        email_code_ttl_seconds=_env_int("EMAIL_CODE_TTL_SECONDS", 600, minimum=30),
        email_code_max_attempts=_env_int("EMAIL_CODE_MAX_ATTEMPTS", 5, minimum=1),
        github_token=(os.environ.get("GITHUB_TOKEN") or "").strip(),
        github_timeout_seconds=_env_float("GITHUB_TIMEOUT_SECONDS", 6.0, minimum=1.0),
        github_sync_interval_seconds=_env_int(
            "GITHUB_SYNC_INTERVAL_SECONDS", 6 * 60 * 60, minimum=60
        ),
        github_sync_enabled=_env_bool("GITHUB_SYNC_ENABLED", True),
    )