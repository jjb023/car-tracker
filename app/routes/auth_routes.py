from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import SESSION_COOKIE, password_matches, redirect_after_login
from ..config import REPO_ROOT

router = APIRouter()
templates = Jinja2Templates(directory=str(REPO_ROOT / "app" / "templates"))


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(
        request, "login.html", {"error": None}
    )


@router.post("/login")
def login_submit(request: Request, password: str = Form(...)):
    if not password_matches(password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Wrong password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return redirect_after_login()


@router.post("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(SESSION_COOKIE)
    return resp