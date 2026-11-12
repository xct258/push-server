"""统一登录（SSO）会话校验：校验 auth-server 签发的服务 Token。

登录页面和登录接口都在 auth-server，本服务不再提供本地登录页。
每个服务独立密码、独立 Cookie、独立签名密钥。

配置（环境变量）：
    AUTH_ENABLED          true/false；默认 true
    SERVICE_ID            服务 ID，例如 push-server
    SERVICE_SECRET        该服务自己的签名密钥
    SERVICE_TOKEN_VERSION 该服务的 Token 版本，默认 1
    SSO_LOGIN_URL         登录页地址，例如 https://auth.o1-1.xct258.top/login
    SSO_COOKIE_NAME       该服务的 Cookie 名，例如 sso_push_server
    SSO_COOKIE_DOMAIN     父域，例如 .o1-1.xct258.top

放行规则：
    - 状态/退出接口、健康检查、SPA 静态资源始终可访问；
    - 服务器上报入口 /api/push 与 TaskOps 同步入口 /api/task* 不要求登录；
    - 页面请求未登录 -> 302 统一登录中心；/api/*、/records -> 401。
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

SERVICE_ID = os.environ.get("SERVICE_ID", "").strip()
SERVICE_SECRET = os.environ.get("SERVICE_SECRET", "")
TOKEN_VERSION = os.environ.get("SERVICE_TOKEN_VERSION", "1").strip()
PUSH_TOKEN = os.environ.get("PUSH_SERVER_TOKEN", "")
COOKIE_NAME = os.environ.get("SSO_COOKIE_NAME", "").strip()
SSO_COOKIE_DOMAIN = os.environ.get("SSO_COOKIE_DOMAIN", "").strip()
SSO_LOGIN_URL = os.environ.get("SSO_LOGIN_URL", "").strip()
SSO_STATE_URL = os.environ.get(
    "SSO_STATE_URL", "http://127.0.0.1:8290/api/auth/service"
).rstrip("/")
AUTH_ENABLED_RAW = os.environ.get("AUTH_ENABLED", "true").strip().lower()

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

router = APIRouter(prefix="/api/auth", tags=["auth"])


def auth_enabled() -> bool:
    if AUTH_ENABLED_RAW in ("1", "true", "yes", "on"):
        return True
    if AUTH_ENABLED_RAW in ("0", "false", "no", "off"):
        return False
    return bool(SERVICE_ID and SERVICE_SECRET and SSO_LOGIN_URL)


def _sign(payload: str) -> str:
    return hmac.new(
        SERVICE_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


_state_lock = threading.Lock()
_state_cache: tuple[float, str | None, bool | None] = (0.0, None, None)


def remote_state() -> tuple[str | None, bool | None]:
    """读取 auth-server 当前 Token 版本；缓存 2 秒，下线约 2 秒内生效。"""
    global _state_cache
    now = time.time()
    with _state_lock:
        expires, version, enabled = _state_cache
    if now < expires:
        return version, enabled

    try:
        url = f"{SSO_STATE_URL}/{quote(SERVICE_ID, safe='')}"
        with urllib.request.urlopen(url, timeout=1.5) as response:
            data = json.loads(response.read().decode("utf-8"))
        version = str(data.get("token_version", "")) or None
        enabled = bool(data.get("enabled"))
    except Exception:
        version = None
        enabled = None

    with _state_lock:
        _state_cache = (now + 2.0, version, enabled)
    return version, enabled


def verify_token(token: str | None) -> bool:
    if not SERVICE_ID or not SERVICE_SECRET or not COOKIE_NAME or not token:
        return False
    parts = token.split(".")
    if len(parts) != 5:
        return False
    version, service_id, token_version, expires, signature = parts
    if version != "v1" or service_id != SERVICE_ID:
        return False
    if not hmac.compare_digest(
        signature, _sign(f"v1.{service_id}.{token_version}.{expires}")
    ):
        return False
    try:
        if int(expires) <= int(time.time()):
            return False
    except ValueError:
        return False

    remote_version, remote_enabled = remote_state()
    if remote_enabled is False:
        return False
    expected_version = remote_version or TOKEN_VERSION
    return token_version == expected_version


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


def login_url() -> str:
    if not SSO_LOGIN_URL:
        return ""
    sep = "&" if "?" in SSO_LOGIN_URL else "?"
    return f"{SSO_LOGIN_URL}{sep}service={quote(SERVICE_ID)}"


def redirect_to_login(request: Request) -> RedirectResponse | JSONResponse:
    base = login_url()
    if not base:
        return JSONResponse(
            {"detail": "未登录，且未配置 SSO_LOGIN_URL"}, status_code=401
        )
    target = _original_url(request)
    sep = "&" if "?" in base else "?"
    return RedirectResponse(
        f"{base}{sep}next={quote(target, safe='')}",
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
        "service": SERVICE_ID,
        "login_url": login_url(),
    }


@router.post("/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        COOKIE_NAME, path="/", domain=SSO_COOKIE_DOMAIN or None
    )
    return response
