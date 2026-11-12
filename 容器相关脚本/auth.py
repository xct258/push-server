"""统一登录（SSO）会话校验：交给 auth-server 集中验签。

登录页面和登录接口都在 auth-server，本服务不保存 SERVICE_SECRET。
每个受保护请求都会带着浏览器 Cookie 调用：

    GET {SSO_VERIFY_URL}?service=<SERVICE_ID>

auth-server 返回 204 放行，401 拒绝。

配置（环境变量）：
    AUTH_ENABLED          true/false；默认 true
    SERVICE_ID            服务 ID，例如 push-server
    SSO_VERIFY_URL        auth-server 验签地址
    SSO_LOGIN_URL         登录页地址
    SSO_COOKIE_NAME       该服务的 Cookie 名
    SSO_COOKIE_DOMAIN     父域，退出登录时清 Cookie

放行规则：
    - 状态/退出接口、健康检查、SPA 静态资源始终可访问；
    - 服务器上报入口 /api/push 与 TaskOps 同步入口 /api/task* 不要求登录；
    - 页面请求未登录 -> 302 统一登录中心；/api/*、/records -> 401。
"""
import hmac
import os
import urllib.error
import urllib.request
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

SERVICE_ID = os.environ.get("SERVICE_ID", "").strip()
PUSH_TOKEN = os.environ.get("PUSH_SERVER_TOKEN", "")
COOKIE_NAME = os.environ.get("SSO_COOKIE_NAME", "").strip()
SSO_COOKIE_DOMAIN = os.environ.get("SSO_COOKIE_DOMAIN", "").strip()
SSO_LOGIN_URL = os.environ.get("SSO_LOGIN_URL", "").strip()
SSO_VERIFY_URL = os.environ.get(
    "SSO_VERIFY_URL", "http://127.0.0.1:8290/api/auth/verify"
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
    return bool(SERVICE_ID and SSO_LOGIN_URL)


def _token_ok(request: Request) -> bool:
    """服务间调用令牌，与浏览器会话互不影响。"""
    return bool(PUSH_TOKEN) and hmac.compare_digest(
        request.headers.get("x-push-token", ""), PUSH_TOKEN
    )


def _auth_server_verify(request: Request) -> bool:
    if not SERVICE_ID or not COOKIE_NAME:
        return False
    cookie = request.headers.get("cookie", "")
    if not cookie:
        return False
    url = f"{SSO_VERIFY_URL}?service={quote(SERVICE_ID, safe='')}"
    req = urllib.request.Request(url, headers={"Cookie": cookie})
    try:
        with urllib.request.urlopen(req, timeout=2.0) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        return exc.code in (204, 304)
    except Exception:
        return False


def is_authenticated(request: Request) -> bool:
    return (
        not auth_enabled()
        or _auth_server_verify(request)
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
