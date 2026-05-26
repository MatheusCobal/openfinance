from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).parents[1] / "static"

router = APIRouter()


@router.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/historico", include_in_schema=False)
def historico():
    return FileResponse(STATIC_DIR / "historico.html")


@router.get("/proximos", include_in_schema=False)
def proximos():
    return FileResponse(STATIC_DIR / "proximos.html")


@router.get("/orcamento", include_in_schema=False)
def orcamento():
    return FileResponse(STATIC_DIR / "orcamento.html")


@router.get("/regras", include_in_schema=False)
def regras():
    return FileResponse(STATIC_DIR / "regras.html")


@router.get("/receita-futura", include_in_schema=False)
def receita_futura():
    return FileResponse(STATIC_DIR / "receita_futura.html")


@router.get("/custos-fixos", include_in_schema=False)
def custos_fixos():
    return FileResponse(STATIC_DIR / "custos_fixos.html")


@router.get("/health")
def health():
    return {"status": "ok"}
