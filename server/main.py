"""深清主题/插件商店后端（FastAPI + SQLite）。

一个进程同时提供：
- /api/*    JSON 接口（认证 / 公开商店 / 开发者中心 / 管理后台 / 桌面端目录）
- /         静态前端（server/static，StaticFiles html=True，SPA 回退）

设计约定：
- 角色：user / developer / admin；
- 主题/插件提交后一律 pending，管理员审核通过才进入公开商店与 /api/catalog.json；
- 评论同样 pending，只有 approved 对外展示并参与评分；
- JWT / 密码哈希全部 stdlib 实现（见 auth.py），不引入第三方认证库。
"""

from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

try:  # 作为包导入：uvicorn server.main:app
    from . import auth, db
    from .config import Settings, load_settings
except ImportError:  # 在 server/ 目录内直接运行：uvicorn main:app
    import auth  # type: ignore
    import db  # type: ignore
    from config import Settings, load_settings  # type: ignore

logger = logging.getLogger("shenqing.store")

#: 合法角色
ROLES = ("user", "developer", "admin")
#: 条目状态
ITEM_STATUSES = ("pending", "approved", "rejected")
#: 条目类型
KINDS = ("theme", "plugin")
#: 主题配色必填键（与桌面端 PALETTE_KEYS 完全一致）
PALETTE_KEYS = ("bgTop", "bgMid", "bgBottom", "accent", "cardBg", "textPrimary")
#: 评论正文上限（与桌面端一致）
MAX_COMMENT_TEXT = 500

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{1,64}$")
USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

ITEM_SELECT = "SELECT " + db.ITEM_COLUMNS + " FROM items i JOIN users u ON u.id = i.author_id"
COMMENT_SELECT = (
    "SELECT c.id, c.item_id, c.user_id, c.rating, c.text, c.status, c.created_at, "
    "u.name AS user_name FROM comments c JOIN users u ON u.id = c.user_id"
)

PLACEHOLDER_HTML = (
    "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
    "<title>深清商店</title>"
    "<body style='font-family:system-ui;background:#05070A;color:#F2F6FF;padding:48px'>"
    "<h1>深清商店 API 已启动</h1>"
    "<p>前端静态文件尚未部署：请把 index.html / app.js / style.css 放进 server/static/。</p>"
    "<p>接口自检：<a style='color:#7FA6FF' href='/api/store/items'>/api/store/items</a> · "
    "<a style='color:#7FA6FF' href='/api/catalog.json'>/api/catalog.json</a> · "
    "<a style='color:#7FA6FF' href='/docs'>/docs</a></p></body></html>"
)


# ========================= 请求体模型 =========================
class RegisterIn(BaseModel):
    email: str = ""
    password: str = ""
    name: str = ""


class LoginIn(BaseModel):
    email: str = ""
    password: str = ""


class ItemIn(BaseModel):
    id: str | None = None
    kind: str = ""
    name: str = ""
    summary: str = ""
    description: str = ""
    version: str = "1.0.0"
    download_url: str = ""
    palette: dict[str, Any] | None = None
    tags: list[str] | None = None
    screenshots: list[str] | None = None


class ItemUpdateIn(BaseModel):
    kind: str | None = None
    name: str | None = None
    summary: str | None = None
    description: str | None = None
    version: str | None = None
    download_url: str | None = None
    palette: dict[str, Any] | None = None
    tags: list[str] | None = None
    screenshots: list[str] | None = None


class CommentIn(BaseModel):
    rating: int = 0
    text: str = ""


class ReviewIn(BaseModel):
    item_id: str | int | None = None
    action: str = ""
    reason: str = ""


class RoleIn(BaseModel):
    role: str = ""


class CommentReviewIn(BaseModel):
    action: str = ""


# ========================= 校验工具 =========================
def _require_text(value: Any, field: str, max_length: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise HTTPException(status_code=400, detail=field + "不能为空")
    if len(text) > max_length:
        raise HTTPException(status_code=400, detail=field + "最多 " + str(max_length) + " 个字符")
    return text


def _normalize_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if not email or len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    return email


def _validate_password(value: Any) -> str:
    password = str(value or "")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if len(password) > auth.MAX_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400, detail="密码最多 " + str(auth.MAX_PASSWORD_LENGTH) + " 位"
        )
    return password


def _validate_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="role 只能是 user / developer / admin")
    return role


def _validate_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="kind 只能是 theme 或 plugin")
    return kind


def _validate_version(value: Any) -> str:
    version = str(value or "").strip() or "1.0.0"
    if len(version) > 32:
        raise HTTPException(status_code=400, detail="版本号最多 32 个字符")
    return version


def _validate_palette(palette: Any, kind: str) -> dict[str, str]:
    """主题必须有 6 个 #RRGGBB 颜色；插件统一存空对象（与桌面端一致）。"""
    if kind != "theme":
        return {}
    if not isinstance(palette, dict):
        raise HTTPException(
            status_code=400,
            detail="主题必须提供 palette 配色对象（" + "、".join(PALETTE_KEYS) + "）",
        )
    result: dict[str, str] = {}
    for key in PALETTE_KEYS:
        value = str(palette.get(key) or "").strip()
        if not COLOR_RE.fullmatch(value):
            raise HTTPException(status_code=400, detail="配色 " + key + " 必须是 #RRGGBB 格式")
        result[key] = value
    return result


def _validate_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise HTTPException(status_code=400, detail="tags 必须是字符串数组")
    result: list[str] = []
    for raw in tags:
        text = str(raw or "").strip()
        if not text:
            continue
        if len(text) > 24:
            raise HTTPException(status_code=400, detail="单个标签最多 24 个字符")
        if text not in result:
            result.append(text)
        if len(result) >= 10:
            break
    return result


def _validate_screenshots(shots: Any) -> list[str]:
    if not shots:
        return []
    if not isinstance(shots, list):
        raise HTTPException(status_code=400, detail="screenshots 必须是字符串数组")
    result: list[str] = []
    for raw in shots:
        text = str(raw or "").strip()
        if not text:
            continue
        if len(text) > 500:
            raise HTTPException(status_code=400, detail="截图地址最多 500 个字符")
        if not (
            text.startswith("http://")
            or text.startswith("https://")
            or (text.startswith("/") and not text.startswith("//"))
        ):
            raise HTTPException(status_code=400, detail="截图地址必须是 http(s) 或站内路径")
        result.append(text)
        if len(result) >= 8:
            break
    return result


def _validate_download_url(kind: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        if kind == "plugin":
            raise HTTPException(status_code=400, detail="插件必须填写 download_url（zip 下载地址）")
        return ""
    if len(text) > 1000:
        raise HTTPException(status_code=400, detail="download_url 最多 1000 个字符")
    if not (
        text.startswith("http://")
        or text.startswith("https://")
        or (text.startswith("/") and not text.startswith("//"))
    ):
        raise HTTPException(status_code=400, detail="download_url 必须是 http(s) 地址或站内绝对路径")
    return text


def _validate_custom_id(value: Any, kind: str) -> str:
    """可选的客户端指定 id（插件应与 plugin.json 的 id 一致）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if not USER_ID_RE.fullmatch(text) or ".." in text:
        raise HTTPException(
            status_code=400,
            detail="id 只能包含字母、数字、点、下划线、短横线，且以字母或数字开头",
        )
    if not text.startswith(("theme-", "plugin-")) and "." not in text and kind == "theme":
        # 允许简短的纯字母主题 id，不做强制前缀；这里只是保留扩展点
        pass
    return text


def _generate_item_id(kind: str) -> str:
    return kind + "-" + uuid.uuid4().hex[:8]


def _normalize_item_id(value: Any) -> str:
    return str(value or "").strip()


# ========================= 依赖：数据库 / 当前用户 =========================
def get_db(request: Request):
    settings: Settings = request.app.state.settings
    conn = db.connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


DB = Annotated[sqlite3.Connection, Depends(get_db)]


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _user_from_token(conn: sqlite3.Connection, settings: Settings, token: str) -> dict | None:
    payload = auth.decode_token(token, settings.secret_key)
    row = conn.execute(
        "SELECT id, email, name, role, created_at FROM users WHERE id = ?",
        (int(str(payload["sub"])),),
    ).fetchone()
    return db.row_to_user(row)


def get_current_user(
    request: Request,
    conn: DB,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    settings: Settings = request.app.state.settings
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user = _user_from_token(conn, settings, token)
    except auth.TokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="登录状态无效：" + str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在或已被删除")
    return user


CurrentUser = Annotated[dict, Depends(get_current_user)]


def get_optional_user(
    request: Request,
    conn: DB,
    authorization: Annotated[str | None, Header()] = None,
) -> dict | None:
    """公开接口用：没带 token 或 token 坏了都当游客，不报错。"""
    settings: Settings = request.app.state.settings
    token = _bearer_token(authorization)
    if not token:
        return None
    try:
        return _user_from_token(conn, settings, token)
    except auth.TokenError:
        return None


OptionalUser = Annotated[dict | None, Depends(get_optional_user)]


def require_roles(*roles: str):
    def dependency(user: CurrentUser) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="没有权限执行该操作")
        return user

    return dependency


require_developer = require_roles("developer", "admin")
require_admin = require_roles("admin")
DeveloperUser = Annotated[dict, Depends(require_developer)]
AdminUser = Annotated[dict, Depends(require_admin)]


# ========================= 序列化辅助 =========================
def _fetch_item(conn: sqlite3.Connection, item_id: str) -> dict | None:
    row = conn.execute(ITEM_SELECT + " WHERE i.id = ?", (item_id,)).fetchone()
    return db.row_to_item(row)


def _fetch_comment(conn: sqlite3.Connection, comment_id: int) -> dict | None:
    row = conn.execute(COMMENT_SELECT + " WHERE c.id = ?", (comment_id,)).fetchone()
    return db.row_to_comment(row)


def _absolute_url(value: str, base: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if text.startswith("/"):
        return base + text
    return urljoin(base + "/", text)


def _catalog_item(item: dict, base: str) -> dict:
    """桌面端 catalog.json 条目：字段与桌面端 normalize_item 对齐。"""
    return {
        "id": item["id"],
        "kind": item["kind"],
        "name": item["name"],
        "author": item["author"],
        "summary": item["summary"],
        "description": item["description"],
        "version": item["version"],
        "rating": item["rating"],
        "downloads": item["downloads"],
        "tags": item["tags"],
        "screenshots": item["screenshots"],
        "download_url": _absolute_url(item["download_url"], base),
        "palette": item["palette"] if item["kind"] == "theme" else {},
        "published_at": item["published_at"],
    }


# ========================= 应用工厂 =========================
class SPAStaticFiles(StaticFiles):
    """静态前端：未知且不像文件的路径回退 index.html；没有前端时给占位页。"""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            normalized = path.replace("\\", "/").strip("/")
            # /api/* 的 404 必须是 JSON，不能回退成前端页面
            if normalized == "api" or normalized.startswith("api/"):
                raise
            if "." in Path(path).name:
                raise
            index = Path(self.directory) / "index.html"
            if index.is_file():
                return FileResponse(index)
            return HTMLResponse(PLACEHOLDER_HTML, status_code=200)


def _bootstrap_admin(settings: Settings) -> None:
    """按 ADMIN_EMAIL / ADMIN_PASSWORD 引导初始管理员（已存在则不动）。"""
    if not settings.bootstrap_admin:
        return
    if not settings.admin_email or not settings.admin_password:
        logger.info("未配置 ADMIN_EMAIL / ADMIN_PASSWORD，跳过初始管理员创建")
        return
    if len(settings.admin_password) < 6:
        logger.warning("ADMIN_PASSWORD 少于 6 位，拒绝创建管理员，请修改环境变量")
        return
    conn = db.connect(settings.database_path)
    try:
        row = conn.execute(
            "SELECT id, role FROM users WHERE email = ?", (settings.admin_email,)
        ).fetchone()
        if row is not None:
            if str(row["role"]) != "admin":
                logger.warning(
                    "ADMIN_EMAIL 已存在且角色不是 admin（当前 %s），未自动提权",
                    row["role"],
                )
            return
        conn.execute(
            "INSERT INTO users (email, password_hash, name, role, created_at) "
            "VALUES (?, ?, ?, 'admin', ?)",
            (
                settings.admin_email,
                auth.hash_password(settings.admin_password),
                "管理员",
                db.utc_now(),
            ),
        )
        conn.commit()
        logger.info("已创建初始管理员：%s", settings.admin_email)
    finally:
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """构造 FastAPI 应用（测试传入临时 Settings 即可完全隔离）。"""
    settings = settings or load_settings()
    db.init_db(settings.database_path)
    _bootstrap_admin(settings)

    application = FastAPI(
        title="深清商店 API",
        description="深清主题 / 插件商店后端：账号、开发者提交、管理员审核、评论、桌面端目录。",
        version=settings.app_version,
    )
    application.state.settings = settings

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    @application.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = str(first.get("msg") or "参数不正确")
        detail = "请求参数不合法：" + (location or "body") + " " + message
        return JSONResponse(status_code=422, content={"detail": detail})

    @application.exception_handler(sqlite3.IntegrityError)
    async def _integrity_handler(request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        logger.warning("数据库约束冲突：%s", exc)
        return JSONResponse(status_code=409, content={"detail": "数据冲突，请检查输入是否重复"})

    router = APIRouter(prefix="/api")

    # ---------------- 认证 ----------------
    @router.post("/auth/register")
    def register(payload: RegisterIn, conn: DB) -> dict:
        email = _normalize_email(payload.email)
        password = _validate_password(payload.password)
        name = _require_text(payload.name, "昵称", 40)
        exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if exists is not None:
            raise HTTPException(status_code=409, detail="该邮箱已注册")
        now = db.utc_now()
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, name, role, created_at) "
            "VALUES (?, ?, ?, 'user', ?)",
            (email, auth.hash_password(password), name, now),
        )
        conn.commit()
        user = {
            "id": int(cursor.lastrowid),
            "email": email,
            "name": name,
            "role": "user",
            "created_at": now,
        }
        token = auth.create_token(user, settings.secret_key, settings.token_ttl_seconds)
        return {"token": token, "user": user}

    @router.post("/auth/login")
    def login(payload: LoginIn, conn: DB) -> dict:
        email = _normalize_email(payload.email)
        row = conn.execute(
            "SELECT id, email, name, role, created_at, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None or not auth.verify_password(str(payload.password or ""), str(row["password_hash"])):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")
        user = {
            "id": int(row["id"]),
            "email": str(row["email"]),
            "name": str(row["name"]),
            "role": str(row["role"]),
            "created_at": str(row["created_at"]),
        }
        token = auth.create_token(user, settings.secret_key, settings.token_ttl_seconds)
        return {"token": token, "user": user}

    @router.get("/auth/me")
    def me(user: CurrentUser) -> dict:
        return user

    # ---------------- 公开商店 ----------------
    @router.get("/store/items")
    def list_store_items(
        conn: DB,
        kind: str = "",
        q: str = "",
        sort: str = "newest",
    ) -> list[dict]:
        conditions = ["i.status = 'approved'"]
        params: list[Any] = []
        if kind:
            conditions.append("i.kind = ?")
            params.append(_validate_kind(kind))
        keyword = str(q or "").strip()
        if keyword:
            if len(keyword) > 100:
                raise HTTPException(status_code=400, detail="搜索关键字最多 100 个字符")
            like = "%" + keyword + "%"
            conditions.append(
                "(i.name LIKE ? COLLATE NOCASE OR i.summary LIKE ? COLLATE NOCASE "
                "OR i.description LIKE ? COLLATE NOCASE OR i.tags_json LIKE ? COLLATE NOCASE "
                "OR u.name LIKE ? COLLATE NOCASE)"
            )
            params.extend([like, like, like, like, like])
        order_by = {
            "rating": "rating DESC, i.downloads DESC, i.created_at DESC, i.id DESC",
            "downloads": "i.downloads DESC, i.created_at DESC, i.id DESC",
            "newest": "i.created_at DESC, i.id DESC",
            "latest": "i.created_at DESC, i.id DESC",
            "oldest": "i.created_at ASC, i.id ASC",
            "name": "i.name COLLATE NOCASE ASC, i.id ASC",
        }.get(str(sort or "").strip().lower(), "i.created_at DESC, i.id DESC")
        sql = ITEM_SELECT + " WHERE " + " AND ".join(conditions) + " ORDER BY " + order_by
        rows = conn.execute(sql, params).fetchall()
        return [db.row_to_item(row) for row in rows]

    @router.get("/store/items/{item_id}")
    def item_detail(item_id: str, conn: DB, user: OptionalUser) -> dict:
        item = _fetch_item(conn, _normalize_item_id(item_id))
        if item is None:
            raise HTTPException(status_code=404, detail="条目不存在")
        if item["status"] != "approved":
            visible = bool(user) and (user["id"] == item["author_id"] or user["role"] == "admin")
            if not visible:
                raise HTTPException(status_code=404, detail="条目不存在或尚未通过审核")
        return item

    @router.get("/store/items/{item_id}/comments")
    def list_comments(item_id: str, conn: DB) -> list[dict]:
        if _fetch_item(conn, _normalize_item_id(item_id)) is None:
            raise HTTPException(status_code=404, detail="条目不存在")
        rows = conn.execute(
            COMMENT_SELECT + " WHERE c.item_id = ? AND c.status = 'approved' "
            "ORDER BY c.created_at DESC, c.id DESC",
            (_normalize_item_id(item_id),),
        ).fetchall()
        return [db.row_to_comment(row) for row in rows]

    @router.post("/store/items/{item_id}/comments")
    def create_comment(item_id: str, payload: CommentIn, conn: DB, user: CurrentUser) -> dict:
        item = _fetch_item(conn, _normalize_item_id(item_id))
        if item is None or item["status"] != "approved":
            raise HTTPException(status_code=404, detail="条目不存在或尚未通过审核")
        rating = int(payload.rating or 0)
        if rating < 1 or rating > 5:
            raise HTTPException(status_code=400, detail="评分必须是 1-5 星")
        text = _require_text(payload.text, "评论内容", MAX_COMMENT_TEXT)
        now = db.utc_now()
        cursor = conn.execute(
            "INSERT INTO comments (item_id, user_id, rating, text, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (item["id"], user["id"], rating, text, now),
        )
        conn.commit()
        comment = _fetch_comment(conn, int(cursor.lastrowid))
        assert comment is not None
        return comment

    # ---------------- 开发者中心 ----------------
    @router.post("/dev/items")
    def create_item(payload: ItemIn, conn: DB, user: DeveloperUser) -> dict:
        kind = _validate_kind(payload.kind)
        name = _require_text(payload.name, "名称", 80)
        summary = _require_text(payload.summary, "一句话简介", 200, required=False)
        description = _require_text(payload.description, "详细说明", 5000, required=False)
        version = _validate_version(payload.version)
        palette = _validate_palette(payload.palette, kind)
        tags = _validate_tags(payload.tags)
        screenshots = _validate_screenshots(payload.screenshots)
        download_url = _validate_download_url(kind, payload.download_url)
        item_id = _validate_custom_id(payload.id, kind) or _generate_item_id(kind)
        if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is not None:
            raise HTTPException(status_code=409, detail="条目 id 已存在：" + item_id)
        now = db.utc_now()
        conn.execute(
            "INSERT INTO items (id, kind, name, summary, description, author_id, version, "
            "download_url, palette_json, tags_json, screenshots_json, status, reject_reason, "
            "downloads, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', 0, ?, ?)",
            (
                item_id,
                kind,
                name,
                summary,
                description,
                user["id"],
                version,
                download_url,
                db.dumps(palette),
                db.dumps(tags),
                db.dumps(screenshots),
                now,
                now,
            ),
        )
        conn.commit()
        item = _fetch_item(conn, item_id)
        assert item is not None
        return item

    @router.get("/dev/items")
    def list_my_items(conn: DB, user: DeveloperUser) -> list[dict]:
        rows = conn.execute(
            ITEM_SELECT + " WHERE i.author_id = ? ORDER BY i.updated_at DESC, i.id DESC",
            (user["id"],),
        ).fetchall()
        return [db.row_to_item(row) for row in rows]

    @router.put("/dev/items/{item_id}")
    def update_item(item_id: str, payload: ItemUpdateIn, conn: DB, user: DeveloperUser) -> dict:
        item = _fetch_item(conn, _normalize_item_id(item_id))
        if item is None:
            raise HTTPException(status_code=404, detail="条目不存在")
        if item["author_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="只能修改自己提交的条目")
        if item["status"] != "pending":
            raise HTTPException(status_code=409, detail="只有待审核的条目可以修改")

        kind = _validate_kind(payload.kind) if payload.kind is not None else item["kind"]
        name = item["name"] if payload.name is None else _require_text(payload.name, "名称", 80)
        summary = (
            item["summary"]
            if payload.summary is None
            else _require_text(payload.summary, "一句话简介", 200, required=False)
        )
        description = (
            item["description"]
            if payload.description is None
            else _require_text(payload.description, "详细说明", 5000, required=False)
        )
        version = item["version"] if payload.version is None else _validate_version(payload.version)
        palette = (
            item["palette"] if payload.palette is None else _validate_palette(payload.palette, kind)
        )
        if kind == "plugin":
            palette = {}
        tags = item["tags"] if payload.tags is None else _validate_tags(payload.tags)
        screenshots = (
            item["screenshots"]
            if payload.screenshots is None
            else _validate_screenshots(payload.screenshots)
        )
        download_url = (
            item["download_url"]
            if payload.download_url is None
            else _validate_download_url(kind, payload.download_url)
        )
        if kind == "plugin" and not download_url:
            raise HTTPException(status_code=400, detail="插件必须填写 download_url（zip 下载地址）")

        conn.execute(
            "UPDATE items SET kind = ?, name = ?, summary = ?, description = ?, version = ?, "
            "download_url = ?, palette_json = ?, tags_json = ?, screenshots_json = ?, "
            "reject_reason = '', updated_at = ? WHERE id = ?",
            (
                kind,
                name,
                summary,
                description,
                version,
                download_url,
                db.dumps(palette),
                db.dumps(tags),
                db.dumps(screenshots),
                db.utc_now(),
                item["id"],
            ),
        )
        conn.commit()
        updated = _fetch_item(conn, item["id"])
        assert updated is not None
        return updated

    # ---------------- 管理后台 ----------------
    def _submissions(conn: sqlite3.Connection, status: str) -> list[dict]:
        status_filter = str(status or "pending").strip().lower() or "pending"
        if status_filter == "all":
            rows = conn.execute(
                ITEM_SELECT + " ORDER BY i.created_at ASC, i.id ASC"
            ).fetchall()
        else:
            if status_filter not in ITEM_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail="status 只能是 pending / approved / rejected / all",
                )
            rows = conn.execute(
                ITEM_SELECT + " WHERE i.status = ? ORDER BY i.created_at ASC, i.id ASC",
                (status_filter,),
            ).fetchall()
        return [db.row_to_item(row) for row in rows]

    @router.get("/admin/submissions")
    def admin_submissions(conn: DB, user: AdminUser, status: str = "pending") -> list[dict]:
        return _submissions(conn, status)

    @router.post("/admin/review")
    def admin_review(payload: ReviewIn, conn: DB, user: AdminUser) -> dict:
        item_id = _normalize_item_id(payload.item_id)
        if not item_id:
            raise HTTPException(status_code=400, detail="缺少 item_id")
        action = str(payload.action or "").strip().lower()
        if action not in ("approve", "reject"):
            raise HTTPException(status_code=400, detail="action 只能是 approve 或 reject")
        item = _fetch_item(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="条目不存在")
        if action == "approve":
            status = "approved"
            reason = ""
        else:
            reason = _require_text(payload.reason, "拒绝原因", 500)
            status = "rejected"
        conn.execute(
            "UPDATE items SET status = ?, reject_reason = ?, updated_at = ? WHERE id = ?",
            (status, reason, db.utc_now(), item_id),
        )
        conn.commit()
        reviewed = _fetch_item(conn, item_id)
        assert reviewed is not None
        return reviewed

    @router.get("/admin/users")
    def admin_users(conn: DB, user: AdminUser) -> list[dict]:
        rows = conn.execute(
            "SELECT id, email, name, role, created_at FROM users ORDER BY id ASC"
        ).fetchall()
        return [db.row_to_user(row) for row in rows]

    @router.post("/admin/users/{user_id}/role")
    def admin_set_role(user_id: int, payload: RoleIn, conn: DB, user: AdminUser) -> dict:
        role = _validate_role(payload.role)
        if int(user_id) == int(user["id"]):
            raise HTTPException(status_code=400, detail="不能修改自己的角色")
        row = conn.execute(
            "SELECT id, email, name, role, created_at FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, int(user_id)))
        conn.commit()
        updated = conn.execute(
            "SELECT id, email, name, role, created_at FROM users WHERE id = ?", (int(user_id),)
        ).fetchone()
        return db.row_to_user(updated) or {}

    @router.get("/admin/comments")
    def admin_comments(conn: DB, user: AdminUser, status: str = "pending") -> list[dict]:
        status_filter = str(status or "pending").strip().lower() or "pending"
        sql = (
            "SELECT c.id, c.item_id, c.user_id, c.rating, c.text, c.status, c.created_at, "
            "u.name AS user_name, i.name AS item_name "
            "FROM comments c JOIN users u ON u.id = c.user_id "
            "JOIN items i ON i.id = c.item_id "
        )
        if status_filter == "all":
            rows = conn.execute(sql + "ORDER BY c.created_at ASC, c.id ASC").fetchall()
        else:
            if status_filter not in ITEM_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail="status 只能是 pending / approved / rejected / all",
                )
            rows = conn.execute(
                sql + "WHERE c.status = ? ORDER BY c.created_at ASC, c.id ASC",
                (status_filter,),
            ).fetchall()
        return [db.row_to_comment(row) for row in rows]

    @router.post("/admin/comments/{comment_id}/review")
    def admin_review_comment(
        comment_id: int, payload: CommentReviewIn, conn: DB, user: AdminUser
    ) -> dict:
        action = str(payload.action or "").strip().lower()
        status = {"approve": "approved", "reject": "rejected"}.get(action)
        if status is None:
            raise HTTPException(status_code=400, detail="action 只能是 approve 或 reject")
        if _fetch_comment(conn, int(comment_id)) is None:
            raise HTTPException(status_code=404, detail="评论不存在")
        conn.execute("UPDATE comments SET status = ? WHERE id = ?", (status, int(comment_id)))
        conn.commit()
        comment = _fetch_comment(conn, int(comment_id))
        assert comment is not None
        return comment

    # ---------------- 桌面端目录 / 健康检查 ----------------
    @router.get("/catalog.json")
    def catalog(request: Request, conn: DB) -> dict:
        rows = conn.execute(
            ITEM_SELECT + " WHERE i.status = 'approved' ORDER BY i.created_at DESC, i.id DESC"
        ).fetchall()
        items = [db.row_to_item(row) for row in rows]
        base = settings.public_base_url or str(request.base_url).rstrip("/")
        updated_at = max((item["updated_at"] for item in items), default=db.utc_now())
        return {
            "version": settings.app_version,
            "updated_at": updated_at,
            "items": [_catalog_item(item, base) for item in items],
        }

    @router.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": settings.app_version, "time": db.utc_now()}

    application.include_router(router)

    # ---------------- 静态前端（必须在 /api 路由之后挂载） ----------------
    static_dir = Path(settings.static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/", SPAStaticFiles(directory=str(static_dir), html=True), name="static")

    return application


app = create_app()
