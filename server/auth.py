"""认证原语：PBKDF2-SHA256 密码哈希 + HS256 JWT，全部 stdlib 实现。

- 密码：pbkdf2_sha256$<iterations>$<b64 salt>$<b64 digest>
- JWT：HS256（hmac + hashlib.sha256），base64url 无填充，三段用点分隔
- 校验签名用 hmac.compare_digest，避免时序侧信道

不依赖任何第三方认证库。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

__all__ = [
    "ALGORITHM",
    "PBKDF2_ITERATIONS",
    "TokenError",
    "b64url_decode",
    "b64url_encode",
    "create_token",
    "decode_token",
    "hash_password",
    "verify_password",
]

#: JWT 算法（只支持这一种；decode 时强校验）
ALGORITHM = "HS256"
#: PBKDF2 迭代次数（云端登录一次约几十毫秒，足够抵抗离线爆破）
PBKDF2_ITERATIONS = 260_000
SALT_BYTES = 16
MAX_PASSWORD_LENGTH = 128


class TokenError(ValueError):
    """token 无效 / 过期 / 签名不对；调用方统一转 401。"""


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256，随机盐，返回可入库的字符串。"""
    if not isinstance(password, str) or not password:
        raise ValueError("密码不能为空")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return (
        "pbkdf2_sha256$"
        + str(PBKDF2_ITERATIONS)
        + "$"
        + b64url_encode(salt)
        + "$"
        + b64url_encode(digest)
    )


def verify_password(password: str, stored: str) -> bool:
    """常量时间校验密码；格式不认识一律 False（不抛异常、不泄露细节）。"""
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(iterations)
        if rounds < 1 or rounds > 10_000_000:
            return False
        salt = b64url_decode(salt_b64)
        expected = b64url_decode(digest_b64)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def _sign(signing_input: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()


def create_token(
    user: dict,
    secret: str,
    ttl_seconds: int,
    *,
    now: float | None = None,
) -> str:
    """签发访问 token；sub 为字符串形式的用户 id。"""
    if not secret:
        raise ValueError("SECRET_KEY 不能为空")
    issued = int(now if now is not None else time.time())
    header = {"alg": ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": str(user["id"]),
        "email": str(user.get("email") or ""),
        "role": str(user.get("role") or "user"),
        "iat": issued,
        "exp": issued + int(ttl_seconds),
        "v": 1,
    }
    header_b64 = b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = b64url_encode(_sign(signing_input, secret))
    return f"{header_b64}.{payload_b64}.{signature}"


def decode_token(token: str, secret: str, *, now: float | None = None) -> dict[str, Any]:
    """校验并解出 payload；任何问题抛 TokenError。"""
    if not token or not isinstance(token, str):
        raise TokenError("缺少 token")
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("token 格式不正确")
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
        signature = b64url_decode(signature_b64)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise TokenError("token 无法解析") from None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise TokenError("token 结构不正确")
    if header.get("alg") != ALGORITHM:
        raise TokenError("不支持的签名算法")
    expected = _sign(f"{header_b64}.{payload_b64}".encode("ascii"), secret)
    if not hmac.compare_digest(signature, expected):
        raise TokenError("token 签名无效")
    expire = payload.get("exp")
    if not isinstance(expire, (int, float)):
        raise TokenError("token 缺少过期时间")
    current = now if now is not None else time.time()
    if current >= float(expire):
        raise TokenError("登录已过期")
    if not str(payload.get("sub") or "").isdigit():
        raise TokenError("token 用户无效")
    return payload
