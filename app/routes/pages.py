from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

STATIC_DIR = Path(__file__).parents[1] / "static"

router = APIRouter()


@router.get("/", include_in_schema=False)
def index():
    return RedirectResponse(url="/custos-fixos", status_code=302)


@router.get("/planejamento", include_in_schema=False)
def planejamento():
    return RedirectResponse(url="/custos-fixos", status_code=302)


@router.get("/historico", include_in_schema=False)
def historico():
    return FileResponse(STATIC_DIR / "historico.html")


@router.get("/proximos", include_in_schema=False)
def proximos():
    return FileResponse(STATIC_DIR / "proximos.html")



@router.get("/orcamento", include_in_schema=False)
def orcamento():
    # Legacy budgets screen — redirects permanently to Planejamento.
    return RedirectResponse(url="/custos-fixos", status_code=307)


@router.get("/regras", include_in_schema=False)
def regras():
    return FileResponse(STATIC_DIR / "regras.html")


@router.get("/receita-futura", include_in_schema=False)
def receita_futura():
    return RedirectResponse(url="/custos-fixos?tab=receita", status_code=307)


@router.get("/custos-fixos", include_in_schema=False)
def custos_fixos():
    return FileResponse(STATIC_DIR / "custos_fixos.html")


@router.get("/health")
def health():
    return {"status": "ok"}
