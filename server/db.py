"""SQLite 存取层（stdlib sqlite3）。

表结构严格对齐商店契约：
- users(id, email, password_hash, name, role, created_at)
- items(id, kind, name, summary, description, author_id, version, download_url,
        palette_json, tags_json, screenshots_json, status, reject_reason,
        downloads, created_at, updated_at)
- comments(id, item_id, user_id, rating, text, status, created_at)
- email_codes(id, email, purpose, code_hash, salt, attempts, created_at,
              expires_at, used_at)

item 的 palette/tags/screenshots 以 JSON 文本存；对外序列化时还原。
邮箱验证码只存 HMAC 摘要（salt 每个验证码独立），成功后立刻置 used_at，
过期/作废后无法再用。
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
    "EMAIL_CODE_MAX_ATTEMPTS",
    "EMAIL_CODE_PURPOSES",
    "EMAIL_CODE_TTL_SECONDS",
    "ITEM_COLUMNS",
    "connect",
    "consume_email_code",
    "create_email_code",
    "dumps",
    "fetch_email_code",
    "hash_email_code",
    "init_db",
    "isoformat",
    "loads",
    "purge_email_codes",
    "row_to_comment",
    "row_to_item",
    "row_to_user",
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
    updated_at       TEXT    NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_items_status      ON items(status);
CREATE INDEX IF NOT EXISTS idx_email_codes       ON email_codes(email, purpose, id);
CREATE INDEX IF NOT EXISTS idx_items_author      ON items(author_id);
CREATE INDEX IF NOT EXISTS idx_comments_item     ON comments(item_id, status);
CREATE INDEX IF NOT EXISTS idx_comments_user     ON comments(user_id);
"""

#: 带作者名与均分评分的 item 查询列（所有读接口共用，保证字段一致）
ITEM_COLUMNS = """
    i.id, i.kind, i.name, i.summary, i.description, i.author_id, i.version,
    i.download_url, i.palette_json, i.tags_json, i.screenshots_json,
    i.status, i.reject_reason, i.downloads, i.created_at, i.updated_at,
    u.name AS author_name,
    COALESCE(
        (SELECT ROUND(AVG(c.rating), 1) FROM comments c
          WHERE c.item_id = i.id AND c.status = 'approved'),
        0
    ) AS rating
"""

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


def init_db(path: str | Path) -> None:
    """建表（幂等）。"""
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
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
