"""SQLite 存取层（stdlib sqlite3）。

表结构严格对齐商店契约：
- users(id, email, password_hash, name, role, created_at)
- items(id, kind, name, summary, description, author_id, version, download_url,
        palette_json, tags_json, screenshots_json, status, reject_reason,
        downloads, created_at, updated_at, platforms,
        github_url, repo_branch, api_version, readme_path, icon_path,
        last_sync_at, last_sync_error)
- comments(id, item_id, user_id, rating, text, status, created_at)
- email_codes(id, email, purpose, code_hash, salt, attempts, created_at,
              expires_at, used_at)
- sync_data(user_id, revision, payload, payload_hash, updated_at, device_name)
- developer_tokens(id, user_id, name, scope, prefix, token_hash, status,
                   created_at, last_used_at, expires_at, revoked_at)

items.platforms 存 JSON 数组（如 ["desktop"] / ["desktop","mobile"]），表示
条目适配的客户端：desktop=电脑端、mobile=手机端；旧库由 init_db 幂等补列，
历史数据按默认值 ["desktop"] 处理。
item 的 palette/tags/screenshots 以 JSON 文本存；对外序列化时还原。
邮箱验证码只存 HMAC 摘要（salt 每个验证码独立），成功后立刻置 used_at，
过期/作废后无法再用。

开发者发布 Token（cwpt_...）与登录 JWT 是两条独立通道：明文只在创建时返回
一次，库里只存 sha256 摘要 + 便于识别的前缀；status/expires_at 决定它还能不能
用来调用开发者提交接口。

items.github_url 是开发者的 GitHub 仓库 / 发布页地址（发布必填），
repo_branch / api_version / readme_path / icon_path 描述发布源结构；
last_sync_at / last_sync_error 记录后台从 GitHub Releases 同步版本的结果。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_PLATFORMS",
    "DEVELOPER_TOKEN_MAX_PER_USER",
    "DEVELOPER_TOKEN_PREFIX",
    "DEVELOPER_TOKEN_SCOPES",
    "EMAIL_CODE_MAX_ATTEMPTS",
    "EMAIL_CODE_PURPOSES",
    "EMAIL_CODE_TTL_SECONDS",
    "GITHUB_SYNC_COLUMNS",
    "ITEM_COLUMNS",
    "ITEM_MIGRATION_COLUMNS",
    "PLATFORMS",
    "apply_github_sync",
    "clear_sync_data",
    "connect",
    "consume_email_code",
    "count_developer_tokens",
    "create_developer_token",
    "create_email_code",
    "developer_token_expired",
    "developer_token_usable",
    "dumps",
    "fail_github_sync",
    "fetch_developer_token",
    "fetch_developer_token_by_hash",
    "fetch_email_code",
    "fetch_sync_data",
    "generate_developer_token",
    "hash_developer_token",
    "hash_email_code",
    "init_db",
    "isoformat",
    "item_platforms",
    "list_developer_tokens",
    "list_github_sync_candidates",
    "loads",
    "purge_email_codes",
    "revoke_developer_token",
    "row_to_comment",
    "row_to_developer_token",
    "row_to_item",
    "row_to_sync",
    "row_to_user",
    "save_sync_data",
    "touch_developer_token",
    "utc_datetime",
    "utc_now",
    "verify_email_code_hash",
]

#: 建表语句；IF NOT EXISTS 保证重复启动安全
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user'
                          CHECK (role IN ('user', 'developer', 'admin')),
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id               TEXT    PRIMARY KEY,
    kind             TEXT    NOT NULL CHECK (kind IN ('theme', 'plugin')),
    name             TEXT    NOT NULL,
    summary          TEXT    NOT NULL DEFAULT '',
    description      TEXT    NOT NULL DEFAULT '',
    author_id        INTEGER NOT NULL REFERENCES users(id),
    version          TEXT    NOT NULL DEFAULT '1.0.0',
    download_url     TEXT    NOT NULL DEFAULT '',
    palette_json     TEXT    NOT NULL DEFAULT '{}',
    tags_json        TEXT    NOT NULL DEFAULT '[]',
    screenshots_json TEXT    NOT NULL DEFAULT '[]',
    status           TEXT    NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'approved', 'rejected')),
    reject_reason    TEXT    NOT NULL DEFAULT '',
    downloads        INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    -- 适配端：JSON 数组，取值只能是 desktop / mobile 的非空子集
    platforms        TEXT    NOT NULL DEFAULT '["desktop"]',
    -- GitHub 发布源：仓库或 releases 页面地址（发布必填）
    github_url       TEXT    NOT NULL DEFAULT '',
    -- 发布源分支（默认 main，供仓库文件读取预留）
    repo_branch      TEXT    NOT NULL DEFAULT 'main',
    -- 发布源声明的 API 版本（可空）
    api_version      TEXT    NOT NULL DEFAULT '',
    -- 发布源里 README / 图标文件相对路径
    readme_path      TEXT    NOT NULL DEFAULT 'README.md',
    icon_path        TEXT    NOT NULL DEFAULT 'icon.png',
    -- 最近一次从 GitHub Releases 同步成功的时间与错误
    last_sync_at     TEXT    NOT NULL DEFAULT '',
    last_sync_error  TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    TEXT    NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    text       TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS email_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT    NOT NULL COLLATE NOCASE,
    purpose    TEXT    NOT NULL
                       CHECK (purpose IN ('register', 'login', 'reset')),
    code_hash  TEXT    NOT NULL,
    salt       TEXT    NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL,
    used_at    TEXT
);

-- 账户云同步：每个账号一条专注数据快照。payload 是客户端自己序列化的 JSON
-- 文本，服务端只保存、不解析结构（端到端加密由客户端负责），因此这里不做
-- JSON 语法约束，只记录 sha256 摘要用于排查/校验。
CREATE TABLE IF NOT EXISTS sync_data (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision     INTEGER NOT NULL DEFAULT 0,
    payload      TEXT    NOT NULL DEFAULT '',
    payload_hash TEXT    NOT NULL DEFAULT '',
    updated_at   INTEGER NOT NULL DEFAULT 0,
    device_name  TEXT    NOT NULL DEFAULT ''
);

-- 开发者发布 Token：给 CI / 脚本用的长期凭据，明文只在创建时返回一次。
-- scope 预留给以后细分权限，目前只有 all（开发者提交/更新条目）。
CREATE TABLE IF NOT EXISTS developer_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL DEFAULT '',
    scope        TEXT    NOT NULL DEFAULT 'all'
                         CHECK (scope IN ('all')),
    prefix       TEXT    NOT NULL DEFAULT '',
    token_hash   TEXT    NOT NULL UNIQUE,
    status       TEXT    NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active', 'revoked')),
    created_at   TEXT    NOT NULL,
    last_used_at TEXT,
    expires_at   TEXT,
    revoked_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_status      ON items(status);
CREATE INDEX IF NOT EXISTS idx_email_codes       ON email_codes(email, purpose, id);
CREATE INDEX IF NOT EXISTS idx_items_author      ON items(author_id);
CREATE INDEX IF NOT EXISTS idx_comments_item     ON comments(item_id, status);
CREATE INDEX IF NOT EXISTS idx_comments_user     ON comments(user_id);
CREATE INDEX IF NOT EXISTS idx_dev_tokens_user   ON developer_tokens(user_id, id);
CREATE INDEX IF NOT EXISTS idx_dev_tokens_hash   ON developer_tokens(token_hash);
"""

#: 带作者名与均分评分的 item 查询列（所有读接口共用，保证字段一致）
ITEM_COLUMNS = """
    i.id, i.kind, i.name, i.summary, i.description, i.author_id, i.version,
    i.download_url, i.palette_json, i.tags_json, i.screenshots_json,
    i.status, i.reject_reason, i.downloads, i.created_at, i.updated_at,
    i.platforms AS platforms,
    i.github_url, i.repo_branch, i.api_version, i.readme_path, i.icon_path,
    i.last_sync_at, i.last_sync_error,
    u.name AS author_name,
    COALESCE(
        (SELECT ROUND(AVG(c.rating), 1) FROM comments c
          WHERE c.item_id = i.id AND c.status = 'approved'),
        0
    ) AS rating
"""

# ========================= 适配端 =========================
#: 适配端：desktop=电脑端、mobile=手机端（顺序固定，序列化时按此排序）
PLATFORMS = ("desktop", "mobile")
#: 未填 / 历史数据的默认适配端
DEFAULT_PLATFORMS = ("desktop",)


def item_platforms(raw: Any) -> list[str]:
    """items.platforms 的 JSON 文本 -> 归一化后的适配端列表。

    只保留 desktop / mobile，去重并按固定顺序排列；坏数据 / 空数组一律回退
    默认值 ["desktop"]，保证任何一条老数据都能被安全解析（接口绝不 500）。
    """
    parsed = loads(raw, [])
    found: list[str] = []
    if isinstance(parsed, list):
        for value in parsed:
            text = str(value or "").strip().lower()
            if text in PLATFORMS and text not in found:
                found.append(text)
    if not found:
        return list(DEFAULT_PLATFORMS)
    return [platform for platform in PLATFORMS if platform in found]


# ========================= 邮箱验证码 =========================
#: 验证码用途：注册 / 验证码登录 / 找回密码
EMAIL_CODE_PURPOSES = ("register", "login", "reset")
#: 验证码有效期（秒）
EMAIL_CODE_TTL_SECONDS = 10 * 60
#: 单个验证码最多尝试次数
EMAIL_CODE_MAX_ATTEMPTS = 5
#: 过期验证码保留多久再物理清理（便于排查，别无限增长）
EMAIL_CODE_RETENTION_SECONDS = 2 * 86400


def utc_datetime(now: datetime | None = None) -> datetime:
    """取 UTC 时间：不传就是当前时间；传入的 naive 时间按 UTC 解释。"""
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def isoformat(moment: datetime | None = None) -> str:
    """datetime -> 与 utc_now() 完全一致的字符串（秒级 + Z 结尾，可直接比较大小）。"""
    return utc_datetime(moment).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_datetime(text: Any) -> datetime | None:
    """解析库里存的 ISO8601 时间串；坏数据返回 None（不抛异常）。"""
    if not text:
        return None
    try:
        return utc_datetime(datetime.fromisoformat(str(text).replace("Z", "+00:00")))
    except ValueError:
        return None


def utc_now() -> str:
    """当前 UTC 时间，ISO8601 秒级（前端/桌面端都按字符串比较，格式必须稳定）。"""
    return isoformat(None)


def connect(path: str | Path) -> sqlite3.Connection:
    """打开 SQLite 连接（WAL + 外键 + 行工厂）。

    注意 check_same_thread=False：FastAPI 的同步生成器依赖（get_db）由 anyio
    线程池执行，依赖的创建与清理可能落在不同工作线程；每个请求仍独占一条连接、
    不会跨请求共享，因此关闭同线程校验是安全的（CPython 的 sqlite3 默认编译为
    serialized 线程模式）。不加这个参数时高并发下会在 conn.close() 抛
    ProgrammingError，表现为偶发 500。
    """
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


#: items 需要幂等补的列：(列名, DDL)。老库缺列时 ALTER TABLE 补上；
#: SQLite 的 ADD COLUMN 支持 NOT NULL + 常量默认值，历史行直接得到默认值。
#: 顺序无关，重复执行安全 —— 列已存在就跳过。
ITEM_MIGRATION_COLUMNS = (
    ("platforms", "TEXT NOT NULL DEFAULT '[\"desktop\"]'"),
    ("github_url", "TEXT NOT NULL DEFAULT ''"),
    ("repo_branch", "TEXT NOT NULL DEFAULT 'main'"),
    ("api_version", "TEXT NOT NULL DEFAULT ''"),
    ("readme_path", "TEXT NOT NULL DEFAULT 'README.md'"),
    ("icon_path", "TEXT NOT NULL DEFAULT 'icon.png'"),
    ("last_sync_at", "TEXT NOT NULL DEFAULT ''"),
    ("last_sync_error", "TEXT NOT NULL DEFAULT ''"),
)


def _migrate_items_columns(conn: sqlite3.Connection) -> None:
    """幂等补列：老库的 items 表缺哪列就补哪列，历史行获得默认值。

    旧条目没有 GitHub 发布源，github_url 补成空串（不会假造地址）；
    平台适配端补成 '["desktop"]'，等价于「旧条目默认电脑端」。
    """
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(items)").fetchall()}
    for name, ddl in ITEM_MIGRATION_COLUMNS:
        if name in columns:
            continue
        conn.execute("ALTER TABLE items ADD COLUMN " + name + " " + ddl)


def init_db(path: str | Path) -> None:
    """建表 + 幂等迁移（重复启动安全）。"""
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate_items_columns(conn)
        conn.commit()
    finally:
        conn.close()


def loads(raw: Any, default: Any) -> Any:
    """把 TEXT 列的 JSON 还原；坏数据回退默认值，绝不让接口 500。"""
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def row_to_user(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "email": str(row["email"]),
        "name": str(row["name"]),
        "role": str(row["role"]),
        "created_at": str(row["created_at"]),
    }


def row_to_item(row: sqlite3.Row | None) -> dict | None:
    """数据库行 -> 对外 item 字典（字段名固定，前端/桌面端都按这套读）。"""
    if row is None:
        return None
    keys = row.keys()
    status = str(row["status"])
    created_at = str(row["created_at"])
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "name": str(row["name"]),
        "summary": str(row["summary"]),
        "description": str(row["description"]),
        "author": str(row["author_name"]) if "author_name" in keys else "",
        "author_id": int(row["author_id"]),
        "version": str(row["version"]),
        "download_url": str(row["download_url"]),
        "palette": loads(row["palette_json"], {}),
        "tags": loads(row["tags_json"], []),
        "screenshots": loads(row["screenshots_json"], []),
        "status": status,
        "reject_reason": str(row["reject_reason"]),
        "downloads": int(row["downloads"]),
        "platforms": item_platforms(row["platforms"] if "platforms" in keys else None),
        # GitHub 发布源（老库/未填时为空串，前端据此决定是否展示链接）
        "github_url": str(row["github_url"]) if "github_url" in keys else "",
        "repo_branch": (str(row["repo_branch"]) if "repo_branch" in keys else "") or "main",
        "api_version": str(row["api_version"]) if "api_version" in keys else "",
        "readme_path": (str(row["readme_path"]) if "readme_path" in keys else "") or "README.md",
        "icon_path": (str(row["icon_path"]) if "icon_path" in keys else "") or "icon.png",
        "last_sync_at": str(row["last_sync_at"]) if "last_sync_at" in keys else "",
        "last_sync_error": str(row["last_sync_error"]) if "last_sync_error" in keys else "",
        "rating": float(row["rating"]) if "rating" in keys else 0.0,
        "created_at": created_at,
        "updated_at": str(row["updated_at"]),
        "published_at": created_at[:10] if status == "approved" else "",
    }


def row_to_comment(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    keys = row.keys()
    comment = {
        "id": int(row["id"]),
        "item_id": str(row["item_id"]),
        "user_id": int(row["user_id"]),
        "user_name": str(row["user_name"]) if "user_name" in keys else "",
        "rating": int(row["rating"]),
        "text": str(row["text"]),
        "status": str(row["status"]),
        "created_at": str(row["created_at"]),
    }
    if "item_name" in keys:
        comment["item_name"] = str(row["item_name"])
    return comment


# ========================= 邮箱验证码：存取与校验 =========================
def hash_email_code(code: str, salt: str) -> str:
    """HMAC-SHA256(salt, code) 十六进制摘要；库里永远不存明文验证码。"""
    return hmac.new(
        str(salt).encode("utf-8"), str(code).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_email_code_hash(code: str, salt: str, stored: str) -> bool:
    """常量时间比较验证码摘要（避免时序侧信道）。"""
    if not stored:
        return False
    return hmac.compare_digest(hash_email_code(code, salt), str(stored))


def create_email_code(
    conn: sqlite3.Connection,
    email: str,
    purpose: str,
    code: str,
    *,
    ttl_seconds: int = EMAIL_CODE_TTL_SECONDS,
    now: datetime | None = None,
) -> dict:
    """写入一条验证码，并作废同一邮箱+用途下尚未使用的旧验证码（只有最新的能用）。"""
    if purpose not in EMAIL_CODE_PURPOSES:
        raise ValueError("不支持的验证码用途：" + str(purpose))
    current = utc_datetime(now)
    ttl = max(1, int(ttl_seconds))
    created_at = isoformat(current)
    expires_at = isoformat(current + timedelta(seconds=ttl))
    salt = secrets.token_hex(16)
    conn.execute(
        "UPDATE email_codes SET used_at = ? "
        "WHERE email = ? AND purpose = ? AND used_at IS NULL",
        (created_at, email, purpose),
    )
    purge_email_codes(conn, now=current)
    conn.execute(
        "INSERT INTO email_codes "
        "(email, purpose, code_hash, salt, attempts, created_at, expires_at, used_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?, NULL)",
        (email, purpose, hash_email_code(code, salt), salt, created_at, expires_at),
    )
    conn.commit()
    return {
        "email": email,
        "purpose": purpose,
        "created_at": created_at,
        "expires_at": expires_at,
        "ttl_seconds": ttl,
    }


def fetch_email_code(
    conn: sqlite3.Connection, email: str, purpose: str
) -> dict | None:
    """取该邮箱+用途下最新的一条未使用验证码（可能已过期，由调用方判断）。"""
    row = conn.execute(
        "SELECT id, email, purpose, code_hash, salt, attempts, created_at, "
        "expires_at, used_at FROM email_codes "
        "WHERE email = ? AND purpose = ? AND used_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (email, purpose),
    ).fetchone()
    return dict(row) if row is not None else None


def consume_email_code(
    conn: sqlite3.Connection,
    email: str,
    purpose: str,
    code: str,
    *,
    max_attempts: int = EMAIL_CODE_MAX_ATTEMPTS,
    now: datetime | None = None,
) -> str:
    """校验并消费验证码。

    返回：
    - "ok"       验证通过（同时置 used_at，用后即废）；
    - "invalid"  不存在 / 已用过 / 已过期 / 验证码不对（对外统一提示）；
    - "too_many" 错误次数达到上限（对外 429）。
    """
    row = fetch_email_code(conn, email, purpose)
    if row is None:
        return "invalid"
    if int(row["attempts"]) >= int(max_attempts):
        return "too_many"
    current = utc_datetime(now)
    expires = _parse_datetime(row["expires_at"])
    if expires is not None and expires <= current:
        conn.execute(
            "UPDATE email_codes SET used_at = ? WHERE id = ?",
            (isoformat(current), int(row["id"])),
        )
        conn.commit()
        return "invalid"
    if verify_email_code_hash(str(code or ""), str(row["salt"]), str(row["code_hash"])):
        conn.execute(
            "UPDATE email_codes SET used_at = ? WHERE id = ?",
            (isoformat(current), int(row["id"])),
        )
        conn.commit()
        return "ok"
    conn.execute(
        "UPDATE email_codes SET attempts = attempts + 1 WHERE id = ?", (int(row["id"]),)
    )
    conn.commit()
    return "invalid"


def discard_email_code(
    conn: sqlite3.Connection, email: str, purpose: str
) -> None:
    """丢弃未使用的验证码（邮件没发出去时调用，避免留下永远收不到的码）。"""
    conn.execute(
        "DELETE FROM email_codes WHERE email = ? AND purpose = ? AND used_at IS NULL",
        (email, purpose),
    )
    conn.commit()


def purge_email_codes(
    conn: sqlite3.Connection,
    *,
    keep_seconds: int = EMAIL_CODE_RETENTION_SECONDS,
    now: datetime | None = None,
) -> int:
    """物理清理过早创建的历史验证码，返回删除行数（表不会无限增长）。"""
    cutoff = isoformat(utc_datetime(now) - timedelta(seconds=max(1, int(keep_seconds))))
    cursor = conn.execute("DELETE FROM email_codes WHERE created_at < ?", (cutoff,))
    conn.commit()
    return int(cursor.rowcount or 0)


# ========================= 账户云同步 =========================
#: 云同步快照的查询列（一个账号最多一条）
SYNC_COLUMNS = "user_id, revision, payload, payload_hash, updated_at, device_name"


def row_to_sync(row: sqlite3.Row | None) -> dict | None:
    """sync_data 行 -> 内部字典（payload 保持原始 JSON 文本，不做解析）。"""
    if row is None:
        return None
    return {
        "user_id": int(row["user_id"]),
        "revision": int(row["revision"]),
        "payload": str(row["payload"]),
        "payload_hash": str(row["payload_hash"]),
        "updated_at": int(row["updated_at"]),
        "device_name": str(row["device_name"]),
    }


def fetch_sync_data(conn: sqlite3.Connection, user_id: int) -> dict | None:
    """取某账号的云同步快照；没有返回 None（对外等价于 revision=0）。"""
    row = conn.execute(
        "SELECT " + SYNC_COLUMNS + " FROM sync_data WHERE user_id = ?", (int(user_id),)
    ).fetchone()
    return row_to_sync(row)


def save_sync_data(
    conn: sqlite3.Connection,
    user_id: int,
    payload_text: str,
    payload_hash: str,
    expected_revision: int,
    device_name: str = "",
    *,
    now: datetime | None = None,
) -> dict | None:
    """乐观并发写入一份新快照。

    - 无快照时 expected_revision 必须是 0，写入后 revision=1；
    - 有快照时 expected_revision 必须等于当前 revision，写入后 revision+1；
    - 不匹配返回 None（调用方转 409 并回传最新 revision），且不改动任何数据。

    并发安全：插入用 ON CONFLICT(user_id) DO NOTHING、更新带
    WHERE revision = expected，两个并发写里落败的一方写不到行（rowcount=0），
    返回 None 让上层重新读最新版本，不会把别人的版本覆盖掉。
    """
    uid = int(user_id)
    expected = int(expected_revision)
    updated_at = int(utc_datetime(now).timestamp())
    row = conn.execute(
        "SELECT revision FROM sync_data WHERE user_id = ?", (uid,)
    ).fetchone()
    if row is None:
        if expected != 0:
            return None
        cursor = conn.execute(
            "INSERT INTO sync_data "
            "(user_id, revision, payload, payload_hash, updated_at, device_name) "
            "VALUES (?, 1, ?, ?, ?, ?) ON CONFLICT(user_id) DO NOTHING",
            (uid, payload_text, payload_hash, updated_at, device_name),
        )
        conn.commit()
        if int(cursor.rowcount or 0) != 1:
            return None
    else:
        if expected != int(row["revision"]):
            return None
        cursor = conn.execute(
            "UPDATE sync_data SET revision = revision + 1, payload = ?, "
            "payload_hash = ?, updated_at = ?, device_name = ? "
            "WHERE user_id = ? AND revision = ?",
            (payload_text, payload_hash, updated_at, device_name, uid, expected),
        )
        conn.commit()
        if int(cursor.rowcount or 0) != 1:
            return None
    return fetch_sync_data(conn, uid)


def clear_sync_data(conn: sqlite3.Connection, user_id: int) -> int:
    """删除某账号的云端快照（只影响本人），返回删除行数。"""
    cursor = conn.execute("DELETE FROM sync_data WHERE user_id = ?", (int(user_id),))
    conn.commit()
    return int(cursor.rowcount or 0)


# ========================= 开发者发布 Token =========================
#: 发布 Token 固定前缀：既方便在请求头/日志里一眼认出，也用来与登录 JWT 分流
DEVELOPER_TOKEN_PREFIX = "cwpt_"
#: 列表里展示的前缀长度（cwpt_ + 8 位），足够区分同账号下的多个 Token
DEVELOPER_TOKEN_PREFIX_LENGTH = len(DEVELOPER_TOKEN_PREFIX) + 8
#: 预留的作用域，目前只有 all（开发者提交 / 更新条目）
DEVELOPER_TOKEN_SCOPES = ("all",)
#: 单个账号最多保留的 Token 数（含已撤销），防止无限增长
DEVELOPER_TOKEN_MAX_PER_USER = 20

DEV_TOKEN_COLUMNS = (
    "id, user_id, name, scope, prefix, token_hash, status, created_at, "
    "last_used_at, expires_at, revoked_at"
)


def hash_developer_token(plain: str) -> str:
    """发布 Token 只存 sha256 摘要；明文只在创建响应里出现一次。"""
    return hashlib.sha256(str(plain or "").encode("utf-8")).hexdigest()


def generate_developer_token() -> tuple[str, str]:
    """生成 (明文, 展示用前缀)：明文形如 cwpt_<43 位随机串>。"""
    plain = DEVELOPER_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return plain, plain[:DEVELOPER_TOKEN_PREFIX_LENGTH]


def row_to_developer_token(row: sqlite3.Row | None) -> dict | None:
    """数据库行 -> 对外 Token 字典（绝不含明文或摘要）。"""
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "name": str(row["name"]),
        "scope": str(row["scope"]),
        "prefix": str(row["prefix"]),
        "status": str(row["status"]),
        "created_at": str(row["created_at"]),
        "last_used_at": str(row["last_used_at"] or ""),
        "expires_at": str(row["expires_at"] or ""),
        "revoked_at": str(row["revoked_at"] or ""),
    }


def create_developer_token(
    conn: sqlite3.Connection,
    user_id: int,
    name: str,
    *,
    scope: str = "all",
    expires_days: int | None = None,
    now: datetime | None = None,
) -> dict:
    """写入一条发布 Token；返回的字典带一次性明文 token 字段。"""
    if scope not in DEVELOPER_TOKEN_SCOPES:
        raise ValueError("不支持的 Token 作用域：" + str(scope))
    plain, prefix = generate_developer_token()
    current = utc_datetime(now)
    created_at = isoformat(current)
    expires_at = ""
    if expires_days:
        expires_at = isoformat(current + timedelta(days=max(1, int(expires_days))))
    cursor = conn.execute(
        "INSERT INTO developer_tokens "
        "(user_id, name, scope, prefix, token_hash, status, created_at, "
        "last_used_at, expires_at, revoked_at) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?, NULL, ?, NULL)",
        (int(user_id), str(name), scope, prefix, hash_developer_token(plain), created_at, expires_at),
    )
    conn.commit()
    record = fetch_developer_token(conn, int(cursor.lastrowid))
    if record is None:  # pragma: no cover - 刚插入的行不可能取不到
        raise RuntimeError("发布 Token 写入失败")
    record["token"] = plain  #: 一次性明文，仅创建时返回
    return record


def fetch_developer_token(conn: sqlite3.Connection, token_id: int) -> dict | None:
    row = conn.execute(
        "SELECT " + DEV_TOKEN_COLUMNS + " FROM developer_tokens WHERE id = ?",
        (int(token_id),),
    ).fetchone()
    return row_to_developer_token(row)


def fetch_developer_token_by_hash(
    conn: sqlite3.Connection, token_hash: str
) -> dict | None:
    """按摘要查 Token（调用方通常还拿不到明文，先算 hash 再查）。"""
    row = conn.execute(
        "SELECT " + DEV_TOKEN_COLUMNS + " FROM developer_tokens WHERE token_hash = ?",
        (str(token_hash or ""),),
    ).fetchone()
    return row_to_developer_token(row)


def list_developer_tokens(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """某账号的全部发布 Token，最近创建的在前（不含明文/摘要）。"""
    rows = conn.execute(
        "SELECT " + DEV_TOKEN_COLUMNS + " FROM developer_tokens "
        "WHERE user_id = ? ORDER BY id DESC",
        (int(user_id),),
    ).fetchall()
    return [row_to_developer_token(row) for row in rows]


def count_developer_tokens(conn: sqlite3.Connection, user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(1) AS total FROM developer_tokens WHERE user_id = ?",
        (int(user_id),),
    ).fetchone()
    return int(row["total"]) if row is not None else 0


def revoke_developer_token(
    conn: sqlite3.Connection, user_id: int, token_id: int, *, now: datetime | None = None
) -> dict | None:
    """撤销自己的 Token（幂等：已撤销的再撤一次返回当前状态）。

    找不到该 Token，或不属于该用户时返回 None（上层统一转 404，避免泄露他人 id）。
    """
    record = fetch_developer_token(conn, token_id)
    if record is None or int(record["user_id"]) != int(user_id):
        return None
    if record["status"] == "active":
        conn.execute(
            "UPDATE developer_tokens SET status = 'revoked', revoked_at = ? WHERE id = ?",
            (isoformat(now), int(token_id)),
        )
        conn.commit()
        record = fetch_developer_token(conn, token_id) or record
    return record


def developer_token_expired(
    record: dict, *, now: datetime | None = None
) -> bool:
    """Token 是否已过期（expires_at 为空表示永久有效）。"""
    expires = _parse_datetime(record.get("expires_at"))
    if expires is None:
        return False
    return expires <= utc_datetime(now)


def developer_token_usable(record: dict, *, now: datetime | None = None) -> tuple[bool, str]:
    """Token 能否使用：返回 (可用, 原因)。原因用于 401 文案。"""
    if record is None:
        return False, "发布 Token 无效"
    if str(record.get("status") or "") != "active":
        return False, "发布 Token 已被撤销"
    if developer_token_expired(record, now=now):
        return False, "发布 Token 已过期"
    return True, ""


def touch_developer_token(
    conn: sqlite3.Connection, token_id: int, *, now: datetime | None = None
) -> None:
    """记录一次成功使用（last_used_at 只精确到秒，够用且稳定）。"""
    conn.execute(
        "UPDATE developer_tokens SET last_used_at = ? WHERE id = ?",
        (isoformat(now), int(token_id)),
    )
    conn.commit()


# ========================= GitHub 发布源同步 =========================
#: 参与同步的条目列（只取同步需要的几列，避免整行搬运）
GITHUB_SYNC_COLUMNS = "i.id, i.name, i.author_id, i.version, i.download_url, i.github_url"


def list_github_sync_candidates(conn: sqlite3.Connection) -> list[dict]:
    """所有「已通过审核」且填了 github_url 的条目（后台同步/手动同步共用）。"""
    rows = conn.execute(
        "SELECT " + GITHUB_SYNC_COLUMNS + " FROM items i "
        "WHERE i.status = 'approved' AND i.github_url <> '' "
        "ORDER BY i.updated_at DESC, i.id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def apply_github_sync(
    conn: sqlite3.Connection,
    item_id: str,
    *,
    version: str,
    download_url: str,
    now: datetime | None = None,
) -> None:
    """同步成功：只更新 version / download_url / last_sync_at / updated_at。

    成功时清空 last_sync_error；其它字段（名称、简介、配色…）一律不动。
    """
    stamp = isoformat(now)
    fields = ["last_sync_at = ?", "last_sync_error = ''", "updated_at = ?"]
    params: list[Any] = [stamp, stamp]
    if str(version or "").strip():
        fields.insert(0, "version = ?")
        params.insert(0, str(version).strip())
    if str(download_url or "").strip():
        fields.insert(1 if str(version or "").strip() else 0, "download_url = ?")
        params.insert(1 if str(version or "").strip() else 0, str(download_url).strip())
    params.append(str(item_id))
    conn.execute("UPDATE items SET " + ", ".join(fields) + " WHERE id = ?", params)
    conn.commit()


def fail_github_sync(
    conn: sqlite3.Connection, item_id: str, error: str
) -> None:
    """同步失败：只写 last_sync_error，条目其它字段（含版本/审核状态）不受影响。"""
    conn.execute(
        "UPDATE items SET last_sync_error = ? WHERE id = ?",
        (str(error or "")[:500], str(item_id)),
    )
    conn.commit()