"""SQLite 存取层（stdlib sqlite3）。

表结构严格对齐商店契约：
- users(id, email, password_hash, name, role, created_at)
- items(id, kind, name, summary, description, author_id, version, download_url,
        palette_json, tags_json, screenshots_json, status, reject_reason,
        downloads, created_at, updated_at)
- comments(id, item_id, user_id, rating, text, status, created_at)

item 的 palette/tags/screenshots 以 JSON 文本存；对外序列化时还原。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "ITEM_COLUMNS",
    "connect",
    "dumps",
    "init_db",
    "loads",
    "row_to_comment",
    "row_to_item",
    "row_to_user",
    "utc_now",
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

CREATE INDEX IF NOT EXISTS idx_items_status      ON items(status);
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


def utc_now() -> str:
    """当前 UTC 时间，ISO8601 秒级（前端/桌面端都按字符串比较，格式必须稳定）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
