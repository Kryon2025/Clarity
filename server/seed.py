"""可选演示数据：3 个主题 + 2 个插件 + 示例开发者/用户 + 若干评论。

用法（仓库根目录）：
    python -m server.seed
或（server/ 目录内）：
    python seed.py

幂等：已存在的邮箱 / 条目 id 会跳过，可以反复执行。
管理员账号仍由服务启动时按 ADMIN_EMAIL / ADMIN_PASSWORD 创建（这里也会顺手补一次）。
"""

from __future__ import annotations

import logging
import sys

try:
    from . import auth, db
    from .config import Settings, load_settings
except ImportError:  # 在 server/ 目录内直接运行
    import auth  # type: ignore
    import db  # type: ignore
    from config import Settings, load_settings  # type: ignore

logger = logging.getLogger("shenqing.store.seed")

PALETTE_AURORA = {
    "bgTop": "#0A1F2E",
    "bgMid": "#06202C",
    "bgBottom": "#04121A",
    "accent": "#35E0C8",
    "cardBg": "#0D2634",
    "textPrimary": "#EAF8FC",
}
PALETTE_SAKURA = {
    "bgTop": "#F6EEF1",
    "bgMid": "#F1E3E9",
    "bgBottom": "#E9D6DE",
    "accent": "#D46A8C",
    "cardBg": "#FFFFFF",
    "textPrimary": "#3A2230",
}
PALETTE_FOREST = {
    "bgTop": "#0C1A12",
    "bgMid": "#08130D",
    "bgBottom": "#050C08",
    "accent": "#5FD08A",
    "cardBg": "#102018",
    "textPrimary": "#E8F6EC",
}

DEMO_USERS = [
    ("dev@example.com", "dev123456", "示例开发者", "developer"),
    ("user@example.com", "user123456", "示例用户", "user"),
    ("aki@example.com", "aki123456", "Aki", "user"),
]

DEMO_ITEMS = [
    {
        "id": "theme-aurora",
        "kind": "theme",
        "name": "极光",
        "summary": "青绿极光掠过深夜海面",
        "description": "以深海为底、极光青绿为强调色的深色主题包，适合夜间专注。\n推荐搭配超禅空间使用。",
        "version": "1.0.0",
        "download_url": "",
        "palette": PALETTE_AURORA,
        "tags": ["深色", "青绿", "夜间"],
        "screenshots": [],
        "downloads": 12840,
    },
    {
        "id": "theme-sakura",
        "kind": "theme",
        "name": "樱雾",
        "summary": "淡粉雾气里的安静书桌",
        "description": "低饱和樱粉浅色主题，配深莓强调色，白天的清空间会更柔和。",
        "version": "1.0.0",
        "download_url": "",
        "palette": PALETTE_SAKURA,
        "tags": ["浅色", "樱粉", "温柔"],
        "screenshots": [],
        "downloads": 9360,
    },
    {
        "id": "theme-forest",
        "kind": "theme",
        "name": "苔原",
        "summary": "安静生长的深林绿",
        "description": "苔藓与湿木的深绿配色，长时间的专注也不会刺眼。",
        "version": "1.0.0",
        "download_url": "",
        "palette": PALETTE_FOREST,
        "tags": ["深色", "森林", "护眼"],
        "screenshots": [],
        "downloads": 7210,
    },
    {
        "id": "com.shenqing.focus_stats",
        "kind": "plugin",
        "name": "专注统计",
        "summary": "把每次专注写进统计，周报自动生成",
        "description": "安装后自动记录专注时长、空间使用分布，并在设置页展示周报。",
        "version": "1.2.0",
        "download_url": "https://raw.githubusercontent.com/Kryon2025/Clarity/store/plugins/com.shenqing.focus_stats.zip",
        "palette": {},
        "tags": ["统计", "周报"],
        "screenshots": [],
        "downloads": 4860,
    },
    {
        "id": "com.shenqing.ambient",
        "kind": "plugin",
        "name": "白噪音",
        "summary": "雨声、篝火与咖啡馆，专注时的背景声",
        "description": "提供多种环境音，可随空间自动切换，音量独立控制。",
        "version": "1.0.3",
        "download_url": "https://raw.githubusercontent.com/Kryon2025/Clarity/store/plugins/com.shenqing.ambient.zip",
        "palette": {},
        "tags": ["白噪音", "氛围"],
        "screenshots": [],
        "downloads": 3520,
    },
]

#: (item_id, 用户邮箱, 评分, 正文, 状态)
DEMO_COMMENTS = [
    ("theme-aurora", "user@example.com", 5, "夜间用真的很舒服，青色不刺眼。", "approved"),
    ("theme-aurora", "aki@example.com", 4, "好看，希望再多一点高光层次。", "approved"),
    ("theme-aurora", "dev@example.com", 5, "自用一年，稳定。", "approved"),
    ("theme-sakura", "user@example.com", 5, "白天用樱粉很温柔。", "approved"),
    ("theme-sakura", "aki@example.com", 4, "浅色里算很耐看的。", "approved"),
    ("theme-forest", "user@example.com", 4, "绿色很护眼。", "approved"),
    ("com.shenqing.focus_stats", "user@example.com", 5, "周报很实用。", "approved"),
    ("com.shenqing.focus_stats", "aki@example.com", 4, "希望能导出 CSV。", "approved"),
    ("com.shenqing.ambient", "user@example.com", 5, "雨声很自然。", "approved"),
    # 待审核评论：管理员登录后能在评论审核里看到
    ("theme-aurora", "aki@example.com", 3, "这条还在待审核，管理员可通过或拒绝。", "pending"),
]


def _ensure_admin(conn, settings: Settings) -> bool:
    """与 main._bootstrap_admin 等价的简化版（seed 独立运行也能建管理员）。"""
    if not settings.admin_email or not settings.admin_password:
        return False
    if len(settings.admin_password) < 6:
        logger.warning("ADMIN_PASSWORD 少于 6 位，跳过管理员创建")
        return False
    row = conn.execute(
        "SELECT id FROM users WHERE email = ?", (settings.admin_email,)
    ).fetchone()
    if row is not None:
        return False
    conn.execute(
        "INSERT INTO users (email, password_hash, name, role, created_at) "
        "VALUES (?, ?, '管理员', 'admin', ?)",
        (settings.admin_email, auth.hash_password(settings.admin_password), db.utc_now()),
    )
    return True


def seed(settings: Settings | None = None) -> dict[str, int]:
    """写入演示数据，返回各项新增数量。"""
    settings = settings or load_settings()
    db.init_db(settings.database_path)
    conn = db.connect(settings.database_path)
    stats = {"users": 0, "items": 0, "comments": 0, "admin": 0}
    try:
        if _ensure_admin(conn, settings):
            stats["admin"] = 1

        ids: dict[str, int] = {}
        for email, password, name, role in DEMO_USERS:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO users (email, password_hash, name, role, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (email, auth.hash_password(password), name, role, db.utc_now()),
                )
                ids[email] = int(cursor.lastrowid)
                stats["users"] += 1
            else:
                ids[email] = int(row["id"])

        # 当前可用作者：优先示例开发者，其次管理员
        author_id = ids["dev@example.com"]
        now = db.utc_now()
        for item in DEMO_ITEMS:
            row = conn.execute("SELECT 1 FROM items WHERE id = ?", (item["id"],)).fetchone()
            if row is not None:
                continue
            conn.execute(
                "INSERT INTO items (id, kind, name, summary, description, author_id, version, "
                "download_url, palette_json, tags_json, screenshots_json, status, reject_reason, "
                "downloads, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', '', ?, ?, ?)",
                (
                    item["id"],
                    item["kind"],
                    item["name"],
                    item["summary"],
                    item["description"],
                    author_id,
                    item["version"],
                    item["download_url"],
                    db.dumps(item["palette"]),
                    db.dumps(item["tags"]),
                    db.dumps(item["screenshots"]),
                    item["downloads"],
                    now,
                    now,
                ),
            )
            stats["items"] += 1

        for item_id, email, rating, text, status in DEMO_COMMENTS:
            user_id = ids.get(email)
            if user_id is None:
                continue
            exists = conn.execute(
                "SELECT 1 FROM comments WHERE item_id = ? AND user_id = ? AND text = ?",
                (item_id, user_id, text),
            ).fetchone()
            if exists is not None:
                continue
            conn.execute(
                "INSERT INTO comments (item_id, user_id, rating, text, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, user_id, int(rating), text, status, now),
            )
            stats["comments"] += 1

        conn.commit()
    finally:
        conn.close()

    logger.info(
        "演示数据完成：新增 %s 个用户 / %s 个条目 / %s 条评论 / 管理员 %s 个",
        stats["users"],
        stats["items"],
        stats["comments"],
        stats["admin"],
    )
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings()
    stats = seed(settings)
    print(
        "演示数据已就绪：新增 {users} 个用户、{items} 个条目、{comments} 条评论、{admin} 个管理员。".format(
            **stats
        )
    )
    print("示例开发者：dev@example.com / dev123456")
    print("示例用户：user@example.com / user123456")
    print("数据库：" + settings.database_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
