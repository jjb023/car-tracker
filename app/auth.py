import hmac
import secrets

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

SESSION_COOKIE = "car_tracker_session"
_serializer = URLSafeTimedSerializer(settings.session_secret, salt="car-tracker-session")


def password_matches(attempt: str) -> bool:
    return secrets.compare_digest(attempt.encode(), settings.app_password.encode())


def make_session_cookie() -> str:
    return _serializer.dumps({"ok": True})


def cookie_valid(token: str) -> bool:
    try:
        _serializer.loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return False
    return True


def is_logged_in(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    return bool(token) and cookie_valid(token)


def require_login(request: Request) -> None:
    """FastAPI dependency: redirect to /login on failure (for HTML routes)."""
    if not is_logged_in(request):
        raise _redirect_to_login(request)


def _redirect_to_login(request: Request) -> HTTPException:
    # HTMX partial requests: tell the client to redirect the whole page.
    if request.headers.get("HX-Request") == "true":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )
    # Ordinary request: 303 to /login.
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/login"},
    )


def require_api_key(request: Request) -> None:
    """FastAPI dependency for /api/*. Accepts X-API-Key header."""
    provided = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(provided.encode(), settings.api_key.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def redirect_after_login() -> RedirectResponse:
    resp = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=make_session_cookie(),
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Cloudflare tunnel terminates TLS; cookie still travels over HTTPS to the client.
    )
    return resp