from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).parents[1] / "static"
PROJECT_ROOT = Path(__file__).parents[2]
REACT_BUILD_DIR = STATIC_DIR / "react"
FRONTEND_SOURCE_INDEX = PROJECT_ROOT / "frontend" / "index.html"

router = APIRouter()


def react_app():
    """Serve the authenticated React app for its internal routes.

    Production Docker builds copy the Vite output to app/static/react.
    The source index fallback keeps route smoke tests and local backend-only
    runs readable before the frontend build has been produced.
    """
    build_index = REACT_BUILD_DIR / "index.html"
    if build_index.is_file():
        return FileResponse(build_index)
    return FileResponse(FRONTEND_SOURCE_INDEX)


@router.get("/", include_in_schema=False)
def index():
    # Public institutional landing page (kept public by the auth middleware).
    # The logged-in app entry point remains /dashboard.
    return FileResponse(STATIC_DIR / "landing.html")


@router.get("/login", include_in_schema=False)
def login_page():
    # Public login screen of the React app (kept public by the auth middleware).
    # Serving the SPA shell here lets a hard refresh / direct hit on /login work.
    return react_app()


@router.get("/dashboard", include_in_schema=False)
def dashboard():
    return react_app()


@router.get("/planejamento", include_in_schema=False)
def planejamento():
    return react_app()


@router.get("/historico", include_in_schema=False)
def historico():
    return react_app()


@router.get("/proximos", include_in_schema=False)
def proximos():
    return react_app()


@router.get("/health")
def health():
    return {"status": "ok"}
