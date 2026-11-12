"""统一登录（SSO）会话校验：校验 auth-server 签发的共享 Cookie。

登录页面和登录接口都在 auth-server，本服务不再提供本地登录页。

配置（环境变量）：
    AUTH_ENABLED      true/false；未设置时：配了 SSO_LOGIN_URL 即开启
    APP_SECRET        会话签名密钥；必须与 auth-server、TaskOps 完全一致
    SSO_LOGIN_URL     统一登录页地址，如 https://auth.example.com/login
                      未登录的页面请求会 302 到这里；接口仍返回 401
    SSO_COOKIE_NAME   Cookie 名，默认 sso_session
    SSO_COOKIE_DOMAIN 父域，如 .example.com（仅退出登录清 Cookie 时使用）

放行规则：
    - 状态/退出接口、健康检查、SPA 静态资源始终可访问；
    - 服务器上报入口 /api/push 与 TaskOps 同步入口 /api/task* 不要求登录；
    - 页面请求未登录 -> 302 统一登录中心；/api/*、/records -> 401。
"""
import hashlib
import hmac
import os
import time
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

PUSH_TOKEN = os.environ.get("PUSH_SERVER_TOKEN", "")
COOKIE_NAME = os.environ.get("SSO_COOKIE_NAME", "sso_session")
SSO_COOKIE_DOMAIN = os.environ.get("SSO_COOKIE_DOMAIN", "").strip()
SSO_LOGIN_URL = os.environ.get("SSO_LOGIN_URL", "").strip()
AUTH_ENABLED_RAW = os.environ.get("AUTH_ENABLED", "").strip().lower()

PUBLIC_PATHS = {
    "/api/auth/status",
    "/api/auth/logout",
    "/api/health",
}
# 服务器脚本上报 + TaskOps 待办同步：保持免登录，写接口另有 X-Push-Token 校验。
PUBLIC_API_PATHS = {"/api/push", "/api/task"}
# 前端静态资源不敏感，放行可避免登录页刷新时 302 掉脚本。
PUBLIC_STATIC_PATHS = {"/favicon.ico", "/favicon.svg"}
PUBLIC_STATIC_PREFIXES = ("/assets/",)

# 与 auth-server 完全一致：只使用共享的 APP_SECRET 校验会话。
SECRET = os.environ.get("APP_SECRET", "").encode("utf-8")

router = APIRouter(prefix="/api/auth", tags=["auth"])


def auth_enabled() -> bool:
    if AUTH_ENABLED_RAW in ("1", "true", "yes", "on"):
        return True
    if AUTH_ENABLED_RAW in ("0", "false", "no", "off"):
        return False
    return bool(SSO_LOGIN_URL)


def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_token(token: str | None) -> bool:
    if not SECRET or not token:
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
    """服务间调用令牌，与浏览器会话互不影响。"""
    return bool(PUSH_TOKEN) and hmac.compare_digest(
        request.headers.get("x-push-token", ""), PUSH_TOKEN
    )


def is_authenticated(request: Request) -> bool:
    return (
        not auth_enabled()
        or verify_token(request.cookies.get(COOKIE_NAME))
        or _token_ok(request)
    )


def _is_api(path: str) -> bool:
    return path == "/records" or path.startswith("/api/")


def _original_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    proto = proto or request.url.scheme
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    url = f"{proto}://{host}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    return url


def redirect_to_login(request: Request) -> RedirectResponse | JSONResponse:
    if not SSO_LOGIN_URL:
        return JSONResponse({"detail": "未登录，且未配置 SSO_LOGIN_URL"}, status_code=401)
    target = _original_url(request)
    sep = "&" if "?" in SSO_LOGIN_URL else "?"
    return RedirectResponse(
        f"{SSO_LOGIN_URL}{sep}next={quote(target, safe='')}",
        status_code=302,
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """统一登录（SSO）：页面跳登录中心，接口返回 401。"""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if (
            not auth_enabled()
            or request.method == "OPTIONS"
            or path in PUBLIC_PATHS
            or path in PUBLIC_API_PATHS
            or path in PUBLIC_STATIC_PATHS
            or path.startswith("/api/task/")
            or path.startswith(PUBLIC_STATIC_PREFIXES)
        ):
            return await call_next(request)
        if is_authenticated(request):
            return await call_next(request)
        if _is_api(path):
            return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
        return redirect_to_login(request)


@router.get("/status")
def auth_status(request: Request):
    return {
        "enabled": auth_enabled(),
        "authenticated": is_authenticated(request),
        "login_url": SSO_LOGIN_URL,
    }


@router.post("/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        COOKIE_NAME, path="/", domain=SSO_COOKIE_DOMAIN or None
    )
    return response
