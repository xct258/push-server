"""管理页访问密码：单密码登录 + HMAC 签名会话 Cookie。

配置（环境变量）：
    APP_PASSWORD     访问密码；未设置或为空 = 不启用页面鉴权（兼容旧部署）
    APP_SECRET       可选，Cookie 签名密钥；不设置则由密码派生
    APP_SESSION_DAYS 会话有效天数，默认 7

放行规则：
    - 登录相关接口、健康检查、SPA 静态资源始终可访问；
    - 服务器上报入口 /api/push 与 TaskOps 同步入口 /api/task* 不要求登录；
    - 其余 /api/*、/records 需要 Cookie 或 X-Push-Token（服务间调用）。
"""
import hashlib
import hmac
import os
import time
from typing import Dict, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

PASSWORD = os.environ.get("APP_PASSWORD", "")
PUSH_TOKEN = os.environ.get("PUSH_SERVER_TOKEN", "")
SESSION_MAX_AGE = int(os.environ.get("APP_SESSION_DAYS", "7")) * 86400
COOKIE_NAME = "push_session"

PUBLIC_PATHS = {
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/health",
}
# 服务器脚本上报 + TaskOps 待办同步：保持免登录，写接口另有 X-Push-Token 校验。
PUBLIC_API_PATHS = {"/api/push", "/api/task"}

SECRET = (
    os.environ.get("APP_SECRET")
    or hashlib.sha256(f"push-session|{PASSWORD}".encode("utf-8")).hexdigest()
).encode("utf-8")

MAX_FAILURES = 5
LOCK_SECONDS = 60
_failures: Dict[str, Tuple[int, float]] = {}

router = APIRouter(prefix="/api/auth", tags=["auth"])


def auth_enabled() -> bool:
    return bool(PASSWORD)


def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_token() -> str:
    payload = f"v1.{int(time.time()) + SESSION_MAX_AGE}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str | None) -> bool:
    if not token or not auth_enabled():
        return False
    try:
        version, expires, signature = token.split(".")
    except ValueError:
        return False
    if version != "v1":
        return False
    if not hmac.compare_digest(signature, _sign(f"v1.{expires}")):
        return False
    try:
        return int(expires) > int(time.time())
    except ValueError:
        return False


def _token_ok(request: Request) -> bool:
    return bool(PUSH_TOKEN) and hmac.compare_digest(
        request.headers.get("x-push-token", ""), PUSH_TOKEN
    )


def is_authenticated(request: Request) -> bool:
    return (
        not auth_enabled()
        or verify_token(request.cookies.get(COOKIE_NAME))
        or _token_ok(request)
    )


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return proto == "https" or request.url.scheme == "https"


def _set_session_cookie(response: JSONResponse, request: Request) -> JSONResponse:
    response.set_cookie(
        COOKIE_NAME,
        create_token(),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )
    return response


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_protected(path: str) -> bool:
    return path == "/records" or path.startswith("/api/")


class AuthMiddleware(BaseHTTPMiddleware):
    """只拦数据接口；管理页 SPA 本身公开，由前端根据登录状态渲染登录页。"""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if (
            not auth_enabled()
            or request.method == "OPTIONS"
            or path in PUBLIC_PATHS
            or path in PUBLIC_API_PATHS
            or path.startswith("/api/task/")
            or not _is_protected(path)
        ):
            return await call_next(request)
        if is_authenticated(request):
            return await call_next(request)
        return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)


class LoginPayload(BaseModel):
    password: str = ""


@router.get("/status")
def auth_status(request: Request):
    return {"enabled": auth_enabled(), "authenticated": is_authenticated(request)}


@router.post("/login")
def auth_login(payload: LoginPayload, request: Request):
    if not auth_enabled():
        return {"ok": True, "enabled": False}

    ip = _client_ip(request)
    now = time.time()
    count, locked_until = _failures.get(ip, (0, 0.0))
    if locked_until > now:
        raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")

    if not hmac.compare_digest(payload.password.encode("utf-8"), PASSWORD.encode("utf-8")):
        count += 1
        if count >= MAX_FAILURES:
            _failures[ip] = (0, now + LOCK_SECONDS)
        else:
            _failures[ip] = (count, 0.0)
        raise HTTPException(status_code=401, detail="密码错误")

    _failures.pop(ip, None)
    return _set_session_cookie(JSONResponse({"ok": True, "enabled": True}), request)


@router.post("/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
