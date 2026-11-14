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
        bootstrap_admin=(os.environ.get("BOOTSTRAP_ADMIN") or "1").strip().lower()
        not in ("0", "false", "no", "off"),
    )
