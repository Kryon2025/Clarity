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

import hashlib
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
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
    from . import auth, db, mailer, ratelimit
    from .config import Settings, load_settings
    from .services import github_sync
except ImportError:  # 在 server/ 目录内直接运行：uvicorn main:app
    import auth  # type: ignore
    import db  # type: ignore
    import mailer  # type: ignore
    import ratelimit  # type: ignore
    from config import Settings, load_settings  # type: ignore
    from services import github_sync  # type: ignore

logger = logging.getLogger("shenqing.store")

#: 合法角色
ROLES = ("user", "developer", "admin")
#: 条目状态
ITEM_STATUSES = ("pending", "approved", "rejected")
#: 条目类型
KINDS = ("theme", "plugin")
#: 适配端：desktop=电脑端、mobile=手机端（与 db.PLATFORMS 一致）
PLATFORMS = ("desktop", "mobile")
#: 未指定时的默认适配端
DEFAULT_PLATFORMS = ["desktop"]
#: 主题配色必填键（与桌面端 PALETTE_KEYS 完全一致）
PALETTE_KEYS = ("bgTop", "bgMid", "bgBottom", "accent", "cardBg", "textPrimary")
#: 评论正文上限（与桌面端一致）
MAX_COMMENT_TEXT = 500
#: 账户云同步：单份 payload 序列化后的字节上限（5MB）
SYNC_MAX_PAYLOAD_BYTES = 5 * 1024 * 1024
#: 账户云同步：设备名最大长度
SYNC_DEVICE_NAME_MAX = 64
#: 验证码用途（与 db.EMAIL_CODE_PURPOSES 保持一致）
CODE_PURPOSES = db.EMAIL_CODE_PURPOSES
#: 对外统一文案：不区分「不存在 / 用过了 / 过期了 / 填错了」
CODE_INVALID_DETAIL = "验证码错误或已过期"
CODE_TOO_MANY_DETAIL = "验证码尝试次数过多，请重新获取"
#: GitHub 发布源地址的必填文案（前端也用同一句，保证提示一致）
GITHUB_URL_REQUIRED_DETAIL = "请填写 GitHub 仓库或发布页地址"
#: 发布 Token 名称上限
TOKEN_NAME_MAX = 60
#: 发布 Token 有效期上限（天）
TOKEN_EXPIRES_DAYS_MAX = 3650
#: 单个账号最多保留的发布 Token 数（含已撤销）
TOKEN_MAX_PER_USER = db.DEVELOPER_TOKEN_MAX_PER_USER
#: 一次同步结果里最多带回多少条错误明细（其余只计数）
SYNC_ERROR_LIMIT = 20

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{1,64}$")
USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
#: 发布源分支名（允许 feature/xxx 这种带斜杠的写法，但不允许空格和 ..）
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")

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
    #: 邮箱验证码（purpose=register）
    code: str = ""


class LoginIn(BaseModel):
    email: str = ""
    password: str = ""


class SendCodeIn(BaseModel):
    email: str = ""
    purpose: str = "register"


class LoginCodeIn(BaseModel):
    email: str = ""
    code: str = ""


class ResetPasswordIn(BaseModel):
    email: str = ""
    code: str = ""
    new_password: str = ""


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
    #: 适配端：["desktop"] / ["mobile"] / ["desktop","mobile"]，缺省 ["desktop"]
    platforms: list[str] | None = None
    #: GitHub 仓库 / 发布页地址（必填，同步版本与下载地址的唯一来源）
    github_url: str = ""
    #: 发布源分支（默认 main）
    repo_branch: str = "main"
    #: 发布源声明的 API 版本（可空）
    api_version: str = ""
    #: 发布源里 README / 图标文件相对路径
    readme_path: str = "README.md"
    icon_path: str = "icon.png"


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
    #: 适配端；None 表示「保持原值」
    platforms: list[str] | None = None
    #: GitHub 发布源；None 表示「保持原值」（必填字段：原值为空时仍会 400）
    github_url: str | None = None
    repo_branch: str | None = None
    api_version: str | None = None
    readme_path: str | None = None
    icon_path: str | None = None


class TokenIn(BaseModel):
    """创建发布 Token：名称必填，expires_days 省略/0 表示永久有效。"""

    name: str = ""
    scope: str = "all"
    expires_days: int | None = None


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


class SyncPutIn(BaseModel):
    """云端快照写入：payload 由客户端自己序列化（服务端不解析结构）。"""

    payload: Any = None
    revision: int = 0
    device: str = ""


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


def _validate_purpose(value: Any) -> str:
    purpose = str(value or "").strip().lower()
    if purpose not in CODE_PURPOSES:
        raise HTTPException(status_code=400, detail="purpose 只能是 register / login / reset")
    return purpose


def _generate_code() -> str:
    """6 位数字验证码（返回字符串，可能带前导 0）。"""
    return str(secrets.randbelow(1_000_000)).zfill(6)


def _consume_code(
    conn: sqlite3.Connection, settings: Settings, email: str, purpose: str, code: Any
) -> None:
    """校验并消费验证码；失败统一 400，错误次数用尽 429。"""
    status = db.consume_email_code(
        conn,
        email,
        purpose,
        str(code or "").strip(),
        max_attempts=settings.email_code_max_attempts,
    )
    if status == "too_many":
        raise HTTPException(status_code=429, detail=CODE_TOO_MANY_DETAIL)
    if status != "ok":
        raise HTTPException(status_code=400, detail=CODE_INVALID_DETAIL)


def _client_ip(request: Request) -> str:
    """限流用的客户端 IP：优先 X-Forwarded-For 第一段（反代部署时才有）。"""
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client is not None else "unknown"


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


def _validate_platforms(value: Any) -> list[str]:
    """校验适配端：必须是 ["desktop","mobile"] 的非空子集。

    缺省（None）返回默认 ["desktop"]；重复值去重，输出按固定顺序排列，
    保证接口与前端展示稳定。
    """
    if value is None:
        return list(DEFAULT_PLATFORMS)
    if not isinstance(value, (list, tuple)):
        raise HTTPException(status_code=400, detail="platforms 必须是字符串数组，可选 desktop / mobile")
    wanted: list[str] = []
    for raw in value:
        text = str(raw or "").strip().lower()
        if text not in PLATFORMS:
            raise HTTPException(
                status_code=400,
                detail="platforms 只能包含 desktop 或 mobile",
            )
        if text not in wanted:
            wanted.append(text)
    if not wanted:
        raise HTTPException(status_code=400, detail="platforms 至少选择一个适配端（desktop / mobile）")
    return [platform for platform in PLATFORMS if platform in wanted]


def _validate_platform_query(value: str) -> str:
    """查询参数 platform：空串表示不过滤；其它值必须合法（否则 400）。"""
    platform = str(value or "").strip().lower()
    if not platform:
        return ""
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail="platform 只能是 desktop 或 mobile")
    return platform


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


def _validate_github_url(value: Any) -> str:
    """GitHub 仓库 / 发布页地址（必填）：只接受 github.com 的仓库或 releases 页面。

    空值和非法地址用同一句文案（README 里约定好的那句），避免前端出现两种提示。
    """
    normalized = github_sync.normalize_github_url(str(value or "").strip())
    if not normalized:
        raise HTTPException(status_code=400, detail=GITHUB_URL_REQUIRED_DETAIL)
    if len(normalized) > 300:
        raise HTTPException(status_code=400, detail="GitHub 地址最多 300 个字符")
    return normalized


def _validate_repo_branch(value: Any) -> str:
    """发布源分支：默认 main，允许 feature/xxx 这种带斜杠的写法。"""
    branch = str(value or "").strip() or "main"
    if not BRANCH_RE.fullmatch(branch) or ".." in branch:
        raise HTTPException(
            status_code=400,
            detail="分支名只能包含字母、数字、点、下划线、短横线与斜杠",
        )
    return branch


def _validate_repo_path(value: Any, field: str, default: str) -> str:
    """发布源内的相对路径（README / 图标）：不允许绝对路径、URL 与 .."""
    text = str(value or "").strip() or default
    if len(text) > 200:
        raise HTTPException(status_code=400, detail=field + "最多 200 个字符")
    if text.startswith(("/", "\\")) or ".." in text or "://" in text:
        raise HTTPException(status_code=400, detail=field + "必须是发布源里的相对路径")
    return text


def _validate_api_version(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) > 32:
        raise HTTPException(status_code=400, detail="API 版本最多 32 个字符")
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


def _sync_payload_text(payload: Any) -> str:
    """校验并序列化云端快照 payload：必须是 JSON 对象，序列化后 ≤ 5MB。

    服务端不理解 payload 的结构（专注记录、设置、端到端加密密文都行），
    只做体积与「必须是对象」两项约束，再原样存库。
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload 必须是 JSON 对象")
    try:
        text = db.dumps(payload)
        size = len(text.encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError):
        raise HTTPException(status_code=400, detail="payload 无法序列化为 JSON") from None
    if size > SYNC_MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="payload 过大：序列化后 "
            + str(size)
            + " 字节，上限 "
            + str(SYNC_MAX_PAYLOAD_BYTES)
            + " 字节（5MB）",
        )
    return text


def _sync_payload_out(text: str) -> Any:
    """库里存的 JSON 文本 -> 响应里的 payload 对象；坏数据返回 None（绝不 500）。"""
    if not text:
        return None
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _guard_sync_write(request: Request, user: dict) -> None:
    """云同步写接口限流：每用户 30 秒最多 10 次（PUT / DELETE 共享）。"""
    limiter = request.app.state.sync_limiter
    allowed, reason, retry_after = limiter.allow(int(user["id"]))
    if not allowed:
        raise HTTPException(
            status_code=429, detail=reason, headers={"Retry-After": str(retry_after)}
        )


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


def _user_from_developer_token(conn: sqlite3.Connection, token: str) -> dict:
    """cwpt_ 发布 Token -> 所属用户。

    校验顺序：存在 -> 未撤销 -> 未过期；通过后刷新 last_used_at，
    这样开发者中心能看出 Token「最后使用」时间。
    """
    record = db.fetch_developer_token_by_hash(conn, db.hash_developer_token(token))
    if record is None:
        raise HTTPException(
            status_code=401,
            detail="发布 Token 无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    usable, reason = db.developer_token_usable(record)
    if not usable:
        raise HTTPException(
            status_code=401, detail=reason, headers={"WWW-Authenticate": "Bearer"}
        )
    row = conn.execute(
        "SELECT id, email, name, role, created_at FROM users WHERE id = ?",
        (int(record["user_id"]),),
    ).fetchone()
    user = db.row_to_user(row)
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在或已被删除")
    db.touch_developer_token(conn, int(record["id"]))
    return user


def get_publisher(
    request: Request,
    conn: DB,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """开发者提交 / 更新接口的身份依赖：登录 JWT 或发布 Token 二选一。

    发布 Token（cwpt_...）走独立校验，不依赖 JWT 有效期，方便 CI 持续发布；
    两种方式都要求账号当前仍是 developer / admin。
    """
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="请先登录，或使用发布 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token.startswith(db.DEVELOPER_TOKEN_PREFIX):
        user = _user_from_developer_token(conn, token)
    else:
        settings: Settings = request.app.state.settings
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
    if user["role"] not in ("developer", "admin"):
        raise HTTPException(status_code=403, detail="没有权限执行该操作")
    return user


PublisherUser = Annotated[dict, Depends(get_publisher)]


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
        #: GitHub 发布源（同步后的版本/下载地址都来自这里；空串表示老条目没填）
        "github_url": item["github_url"],
        "last_sync_at": item["last_sync_at"],
        "palette": item["palette"] if item["kind"] == "theme" else {},
        "platforms": list(item["platforms"]),
        "published_at": item["published_at"],
    }


# ========================= GitHub 发布源同步 =========================
class GitHubSyncState:
    """最近一轮 GitHub 同步的运行状态（进程内，重启重置）。

    条目级结果落库（items.last_sync_at / last_sync_error）；这里保留最近一次
    同步的统计与错误明细，供 GET /api/admin/sync/status 与开发者中心读取。
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.last_run_at = ""
        self.last_run_seconds = 0.0
        self.total = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.errors: list[dict] = []

    def begin(self) -> bool:
        """抢占一轮同步；已有一轮在跑时返回 False（手动与定时不叠加）。"""
        with self.lock:
            if self.running:
                return False
            self.running = True
            return True

    def finish(self, summary: dict) -> None:
        with self.lock:
            self.running = False
            self.last_run_at = str(summary.get("finished_at") or "")
            self.last_run_seconds = float(summary.get("seconds") or 0.0)
            self.total = int(summary.get("total") or 0)
            self.success = int(summary.get("success") or 0)
            self.failed = int(summary.get("failed") or 0)
            self.skipped = int(summary.get("skipped") or 0)
            self.errors = list(summary.get("errors") or [])

    def snapshot(self, settings: Settings) -> dict:
        with self.lock:
            return {
                "ok": True,
                "running": self.running,
                "enabled": bool(settings.github_sync_enabled),
                "interval_seconds": int(settings.github_sync_interval_seconds),
                "last_run_at": self.last_run_at,
                "last_run_seconds": round(self.last_run_seconds, 3),
                "total": self.total,
                "success": self.success,
                "failed": self.failed,
                "skipped": self.skipped,
                "errors": list(self.errors),
            }


def run_github_sync(settings: Settings, state: GitHubSyncState) -> dict:
    """同步所有「已通过审核 + 填了 github_url」的条目，返回统计（同步执行）。

    - 成功：只更新 version / download_url / last_sync_at / updated_at；
      开发者留空的版本（含 0.0.0）在首次同步时自动补齐；
    - 失败：只写 last_sync_error，不改版本、不改审核状态、不影响条目展示；
    - 单个条目失败不会中断整轮同步。
    """
    started = time.monotonic()
    summary: dict[str, Any] = {
        "ok": True,
        "started_at": db.utc_now(),
        "finished_at": "",
        "seconds": 0.0,
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }
    conn = None
    try:
        conn = db.connect(settings.database_path)
        candidates = db.list_github_sync_candidates(conn)
        summary["total"] = len(candidates)
        for item in candidates:
            item_id = str(item["id"])
            result = github_sync.sync_item(
                item,
                token=settings.github_token,
                timeout=settings.github_timeout_seconds,
            )
            if not result["ok"]:
                summary["failed"] += 1
                db.fail_github_sync(conn, item_id, result["error"])
                logger.warning("GitHub 同步失败（%s）：%s", item_id, result["error"])
                if len(summary["errors"]) < SYNC_ERROR_LIMIT:
                    summary["errors"].append(
                        {"item_id": item_id, "name": str(item["name"]), "error": result["error"]}
                    )
                continue
            db.apply_github_sync(
                conn,
                item_id,
                version=result["version"],
                download_url=result["download_url"],
            )
            summary["success"] += 1
    except Exception as exc:  # noqa: BLE001 - 同步失败不能拖垮服务或后台线程
        summary["ok"] = False
        summary["error"] = str(exc)
        logger.exception("GitHub 同步异常中止")
    finally:
        if conn is not None:
            conn.close()
        summary["finished_at"] = db.utc_now()
        summary["seconds"] = round(time.monotonic() - started, 3)
        state.finish(summary)
    logger.info(
        "GitHub 同步完成：共 %s 个条目，成功 %s，失败 %s",
        summary["total"],
        summary["success"],
        summary["failed"],
    )
    return summary


def _github_sync_loop(
    settings: Settings, state: GitHubSyncState, stop_event: threading.Event
) -> None:
    """后台线程：每 GITHUB_SYNC_INTERVAL_SECONDS（默认 6 小时）同步一轮。"""
    interval = max(60, int(settings.github_sync_interval_seconds))
    logger.info("GitHub 后台同步已启动：每 %s 小时一轮", round(interval / 3600.0, 2))
    while not stop_event.wait(interval):
        if not state.begin():
            logger.info("上一轮 GitHub 同步还没结束，跳过本轮")
            continue
        run_github_sync(settings, state)


def _start_github_sync_thread(application: FastAPI) -> None:
    """启动后台同步线程（daemon；测试可用 GITHUB_SYNC_ENABLED=0 关掉）。"""
    settings: Settings = application.state.settings
    if not settings.github_sync_enabled:
        logger.info("GITHUB_SYNC_ENABLED=0：跳过后台 GitHub 同步线程")
        return
    state: GitHubSyncState = application.state.github_sync
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_github_sync_loop,
        args=(settings, state, stop_event),
        name="shenqing-github-sync",
        daemon=True,
    )
    application.state.github_sync_stop = stop_event
    application.state.github_sync_thread = thread
    thread.start()


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
    #: 邮件配置（启动时快照；未配置 SMTP 即开发模式）
    mail_config = mailer.config_from_settings(settings)
    application.state.mail_config = mail_config
    #: 发送限流（纯内存，进程重启即重置）
    application.state.send_limiter = ratelimit.SendRateLimiter()
    #: 账户云同步写入限流（纯内存，进程重启即重置）
    application.state.sync_limiter = ratelimit.SyncWriteRateLimiter()
    #: GitHub 发布源同步状态（进程内；条目级结果落库）
    application.state.github_sync = GitHubSyncState()

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
    @router.post("/auth/send-code")
    def send_code(payload: SendCodeIn, request: Request, conn: DB) -> dict:
        """发送邮箱验证码（注册 / 验证码登录 / 找回密码）。"""
        email = _normalize_email(payload.email)
        purpose = _validate_purpose(payload.purpose)

        limiter = request.app.state.send_limiter
        allowed, reason, retry_after = limiter.allow(email, _client_ip(request))
        if not allowed:
            raise HTTPException(
                status_code=429, detail=reason, headers={"Retry-After": str(retry_after)}
            )

        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if purpose == "register" and row is not None:
            raise HTTPException(status_code=400, detail="该邮箱已注册，请直接登录或找回密码")
        ttl = int(settings.email_code_ttl_seconds)
        if purpose != "register" and row is None:
            # 防枚举：账号不存在也返回成功，只写日志
            logger.info("验证码请求：邮箱 %s 不存在（%s），按防枚举策略仍返回成功", email, purpose)
            return {"ok": True, "ttl_seconds": ttl}

        code = _generate_code()
        db.create_email_code(conn, email, purpose, code, ttl_seconds=ttl)
        try:
            mailer.send_code(mail_config, email, purpose, code, ttl)
        except mailer.MailError as exc:
            # 没发出去就别留下一个永远收不到的验证码，也不能抛 500
            db.discard_email_code(conn, email, purpose)
            logger.warning("验证码邮件发送失败（%s / %s）：%s", email, purpose, exc)
            raise HTTPException(status_code=503, detail=str(exc)) from None

        result = {"ok": True, "ttl_seconds": ttl}
        if mailer.is_dev_mode(mail_config):
            # 仅开发模式返回，正式部署（已配置 SMTP 且未开 MAIL_DEV_MODE）不会出现
            result["dev_code"] = code
        return result

    @router.post("/auth/register")
    def register(payload: RegisterIn, conn: DB) -> dict:
        email = _normalize_email(payload.email)
        password = _validate_password(payload.password)
        name = _require_text(payload.name, "昵称", 40)
        exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if exists is not None:
            raise HTTPException(status_code=409, detail="该邮箱已注册")
        # 邮箱验证码：purpose=register，用后即废
        _consume_code(conn, settings, email, "register", payload.code)
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

    @router.post("/auth/login-code")
    def login_code(payload: LoginCodeIn, conn: DB) -> dict:
        """验证码登录（邮箱 + purpose=login 的验证码）。"""
        email = _normalize_email(payload.email)
        _consume_code(conn, settings, email, "login", payload.code)
        row = conn.execute(
            "SELECT id, email, name, role, created_at FROM users WHERE email = ?", (email,)
        ).fetchone()
        user = db.row_to_user(row)
        if user is None:
            raise HTTPException(status_code=401, detail="账号不存在或已被删除")
        token = auth.create_token(user, settings.secret_key, settings.token_ttl_seconds)
        return {"token": token, "user": user}

    @router.post("/auth/reset-password")
    def reset_password(payload: ResetPasswordIn, conn: DB) -> dict:
        """用邮箱验证码重置密码（purpose=reset）。"""
        email = _normalize_email(payload.email)
        # 先校验新密码，避免因为密码不合格白白消耗掉验证码
        new_password = _validate_password(payload.new_password)
        _consume_code(conn, settings, email, "reset", payload.code)
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            # 验证码有效但账号已不存在：仍用统一文案，不泄露账号信息
            raise HTTPException(status_code=400, detail=CODE_INVALID_DETAIL)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (auth.hash_password(new_password), int(row["id"])),
        )
        conn.commit()
        logger.info("用户 %s 通过邮箱验证码重置了密码", email)
        return {"ok": True}

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
        platform: str = "",
    ) -> list[dict]:
        conditions = ["i.status = 'approved'"]
        params: list[Any] = []
        if kind:
            conditions.append("i.kind = ?")
            params.append(_validate_kind(kind))
        selected_platform = _validate_platform_query(platform)
        if selected_platform:
            # platforms 是 JSON 数组文本，这里按「带引号的完整取值」匹配，
            # 不依赖 SQLite JSON1 扩展，老库新库行为一致。
            conditions.append("i.platforms LIKE ?")
            params.append('%"' + selected_platform + '"%')
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
    def create_item(payload: ItemIn, conn: DB, user: PublisherUser) -> dict:
        """提交条目：github_url 必填，其余发布源字段有默认值。

        身份可以是登录 JWT，也可以是开发者发布 Token（Authorization: Bearer cwpt_...），
        方便 CI / 脚本持续发布。
        """
        kind = _validate_kind(payload.kind)
        name = _require_text(payload.name, "名称", 80)
        summary = _require_text(payload.summary, "一句话简介", 200, required=False)
        description = _require_text(payload.description, "详细说明", 5000, required=False)
        version = _validate_version(payload.version)
        palette = _validate_palette(payload.palette, kind)
        tags = _validate_tags(payload.tags)
        screenshots = _validate_screenshots(payload.screenshots)
        platforms = _validate_platforms(payload.platforms)
        download_url = _validate_download_url(kind, payload.download_url)
        github_url = _validate_github_url(payload.github_url)
        repo_branch = _validate_repo_branch(payload.repo_branch)
        api_version = _validate_api_version(payload.api_version)
        readme_path = _validate_repo_path(payload.readme_path, "README 路径", "README.md")
        icon_path = _validate_repo_path(payload.icon_path, "图标路径", "icon.png")
        item_id = _validate_custom_id(payload.id, kind) or _generate_item_id(kind)
        if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is not None:
            raise HTTPException(status_code=409, detail="条目 id 已存在：" + item_id)
        now = db.utc_now()
        conn.execute(
            "INSERT INTO items (id, kind, name, summary, description, author_id, version, "
            "download_url, palette_json, tags_json, screenshots_json, status, reject_reason, "
            "downloads, created_at, updated_at, platforms, github_url, repo_branch, "
            "api_version, readme_path, icon_path, last_sync_at, last_sync_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', 0, ?, ?, ?, ?, ?, ?, ?, ?, '', '')",
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
                db.dumps(platforms),
                github_url,
                repo_branch,
                api_version,
                readme_path,
                icon_path,
            ),
        )
        conn.commit()
        item = _fetch_item(conn, item_id)
        assert item is not None
        logger.info("开发者 %s 提交条目 %s（GitHub 发布源 %s）", user["email"], item_id, github_url)
        return item

    @router.get("/dev/items")
    def list_my_items(conn: DB, user: DeveloperUser) -> list[dict]:
        rows = conn.execute(
            ITEM_SELECT + " WHERE i.author_id = ? ORDER BY i.updated_at DESC, i.id DESC",
            (user["id"],),
        ).fetchall()
        return [db.row_to_item(row) for row in rows]

    @router.put("/dev/items/{item_id}")
    def update_item(item_id: str, payload: ItemUpdateIn, conn: DB, user: PublisherUser) -> dict:
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
        platforms = (
            item["platforms"]
            if payload.platforms is None
            else _validate_platforms(payload.platforms)
        )
        # GitHub 发布源：不传表示保持原值；原值为空（老条目）时仍然要求补填
        github_url = (
            item["github_url"]
            if payload.github_url is None
            else _validate_github_url(payload.github_url)
        )
        if not github_url:
            raise HTTPException(status_code=400, detail=GITHUB_URL_REQUIRED_DETAIL)
        repo_branch = (
            item["repo_branch"]
            if payload.repo_branch is None
            else _validate_repo_branch(payload.repo_branch)
        )
        api_version = (
            item["api_version"]
            if payload.api_version is None
            else _validate_api_version(payload.api_version)
        )
        readme_path = (
            item["readme_path"]
            if payload.readme_path is None
            else _validate_repo_path(payload.readme_path, "README 路径", "README.md")
        )
        icon_path = (
            item["icon_path"]
            if payload.icon_path is None
            else _validate_repo_path(payload.icon_path, "图标路径", "icon.png")
        )
        # 换了发布源地址就清掉旧的同步错误，等下一轮同步重新校验
        reset_sync_error = ", last_sync_error = ''" if github_url != item["github_url"] else ""

        conn.execute(
            "UPDATE items SET kind = ?, name = ?, summary = ?, description = ?, version = ?, "
            "download_url = ?, palette_json = ?, tags_json = ?, screenshots_json = ?, "
            "platforms = ?, github_url = ?, repo_branch = ?, api_version = ?, "
            "readme_path = ?, icon_path = ?, reject_reason = '', updated_at = ?"
            + reset_sync_error
            + " WHERE id = ?",
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
                db.dumps(platforms),
                github_url,
                repo_branch,
                api_version,
                readme_path,
                icon_path,
                db.utc_now(),
                item["id"],
            ),
        )
        conn.commit()
        updated = _fetch_item(conn, item["id"])
        assert updated is not None
        return updated

    # ---------------- 开发者发布 Token ----------------
    @router.post("/dev/tokens")
    def create_dev_token(payload: TokenIn, conn: DB, user: DeveloperUser) -> dict:
        """创建发布 Token：响应里带一次性明文 cwpt_...（之后只存 sha256）。"""
        name = _require_text(payload.name, "Token 名称", TOKEN_NAME_MAX)
        scope = str(payload.scope or "all").strip().lower() or "all"
        if scope not in db.DEVELOPER_TOKEN_SCOPES:
            raise HTTPException(status_code=400, detail="scope 目前只支持 all")
        expires_days = payload.expires_days
        if expires_days is not None:
            if expires_days < 0 or expires_days > TOKEN_EXPIRES_DAYS_MAX:
                raise HTTPException(
                    status_code=400,
                    detail="expires_days 必须在 0 到 " + str(TOKEN_EXPIRES_DAYS_MAX) + " 天之间（0 表示永久）",
                )
            if expires_days == 0:
                expires_days = None
        if db.count_developer_tokens(conn, int(user["id"])) >= TOKEN_MAX_PER_USER:
            raise HTTPException(
                status_code=400,
                detail="发布 Token 数量已达上限（" + str(TOKEN_MAX_PER_USER) + " 个），请先撤销不用的",
            )
        record = db.create_developer_token(
            conn,
            int(user["id"]),
            name,
            scope=scope,
            expires_days=expires_days,
        )
        logger.info("开发者 %s 创建发布 Token %s", user["email"], record["prefix"])
        return record

    @router.get("/dev/tokens")
    def list_dev_tokens(conn: DB, user: DeveloperUser) -> list[dict]:
        """我的发布 Token：只有前缀/状态/时间，绝不会返回明文或摘要。"""
        return db.list_developer_tokens(conn, int(user["id"]))

    @router.post("/dev/tokens/{token_id}/revoke")
    def revoke_dev_token(token_id: int, conn: DB, user: DeveloperUser) -> dict:
        """撤销发布 Token（幂等）：撤销后立即不能用于提交/更新条目。"""
        record = db.revoke_developer_token(conn, int(user["id"]), int(token_id))
        if record is None:
            raise HTTPException(status_code=404, detail="发布 Token 不存在")
        logger.info("开发者 %s 撤销发布 Token %s", user["email"], record["prefix"])
        return record

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

    @router.post("/admin/sync")
    def admin_sync(request: Request, user: AdminUser) -> dict:
        """立即同步所有已通过审核条目的 GitHub 版本（同步执行，返回统计）。"""
        state: GitHubSyncState = request.app.state.github_sync
        if not state.begin():
            raise HTTPException(status_code=409, detail="同步正在进行中，请稍后再试")
        return run_github_sync(request.app.state.settings, state)

    @router.get("/admin/sync/status")
    def admin_sync_status(request: Request, user: AdminUser) -> dict:
        """上次同步时间 / 成功数 / 失败数 / 错误明细。"""
        return request.app.state.github_sync.snapshot(request.app.state.settings)

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

    # ---------------- 账户云同步（跨设备同步专注数据） ----------------
    @router.get("/sync")
    def get_sync(conn: DB, user: CurrentUser) -> dict:
        """读取本账号的云端快照；没有数据时 revision=0、payload=null。"""
        row = db.fetch_sync_data(conn, int(user["id"]))
        if row is None:
            return {
                "revision": 0,
                "updated_at": 0,
                "payload": None,
                "device_name": "",
            }
        return {
            "revision": int(row["revision"]),
            "updated_at": int(row["updated_at"]),
            "payload": _sync_payload_out(str(row["payload"])),
            "device_name": str(row["device_name"]),
        }

    @router.put("/sync")
    def put_sync(payload: SyncPutIn, request: Request, conn: DB, user: CurrentUser):
        """写入云端快照（乐观并发）：revision 必须等于服务端当前版本，否则 409。

        revision 规则：首次写入传 0，成功后返回 1；之后每次成功 +1。
        409 的响应体里带最新 revision，客户端据此决定覆盖还是先拉取。
        """
        _guard_sync_write(request, user)
        expected = int(payload.revision or 0)
        if expected < 0:
            raise HTTPException(status_code=400, detail="revision 不能为负数")
        text = _sync_payload_text(payload.payload)
        device = _require_text(payload.device, "device", SYNC_DEVICE_NAME_MAX, required=False)
        row = db.save_sync_data(
            conn,
            int(user["id"]),
            text,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            expected,
            device,
        )
        if row is None:
            latest = db.fetch_sync_data(conn, int(user["id"]))
            latest_revision = int(latest["revision"]) if latest is not None else 0
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "revision 不匹配：服务端当前版本为 "
                    + str(latest_revision)
                    + "，请先拉取最新数据",
                    "revision": latest_revision,
                },
            )
        return {"revision": int(row["revision"]), "updated_at": int(row["updated_at"])}

    @router.delete("/sync")
    def delete_sync(request: Request, conn: DB, user: CurrentUser) -> dict:
        """清空本账号的云端快照（只影响本人），删除后版本回到 0。"""
        _guard_sync_write(request, user)
        db.clear_sync_data(conn, int(user["id"]))
        return {"ok": True, "revision": 0}

    # ---------------- 桌面端目录 / 健康检查 ----------------
    @router.get("/catalog.json")
    def catalog(request: Request, conn: DB, platform: str = "") -> dict:
        """桌面端目录：platform=desktop / mobile 时只返回适配该端的条目。"""
        sql = ITEM_SELECT + " WHERE i.status = 'approved'"
        params: list[Any] = []
        selected_platform = _validate_platform_query(platform)
        if selected_platform:
            sql += " AND i.platforms LIKE ?"
            params.append('%"' + selected_platform + '"%')
        rows = conn.execute(sql + " ORDER BY i.created_at DESC, i.id DESC", params).fetchall()
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

    # ---------------- 后台 GitHub 同步线程（默认每 6 小时一轮） ----------------
    _start_github_sync_thread(application)

    return application


app = create_app()