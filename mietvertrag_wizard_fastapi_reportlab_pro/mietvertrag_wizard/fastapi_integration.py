from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .pdf_reportlab import build_contract_pdf


def mount_fastapi(
    app: FastAPI,
    *,
    mount_path: str = "/mietvertrag",
    static_path: str = "/mietvertrag/static",
    template_name: str = "mietvertrag_wizard/index.html",
) -> None:
    """Mountet den Wizard (UI) und serverseitige PDF-Endpunkte in eine bestehende FastAPI-App.

    Endpunkte:
      - GET  {mount_path}            -> Wizard UI
      - POST {mount_path}/api/pdf    -> PDF (serverseitig, ReportLab)

    Statische Assets:
      - {static_path}/mietvertrag_wizard/...
    """

    pkg_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(pkg_dir / "templates"))

    app.mount(static_path, StaticFiles(directory=str(pkg_dir / "static")), name="mietvertrag_wizard_static")

    # Router unter mount_path als Prefix (so bleiben API-URLs stabil)
    base = mount_path.rstrip("/") or "/mietvertrag"
    router = APIRouter(prefix=base)

    @router.get("/", response_class=HTMLResponse)
    @router.get("", response_class=HTMLResponse)
    async def wizard(request: Request):
        return templates.TemplateResponse(
            template_name,
            {
                "request": request,
                "static_prefix": static_path.rstrip("/") + "/mietvertrag_wizard",
                "api_base": base + "/api",
            },
        )

    @router.post("/api/pdf")
    async def pdf_endpoint(payload: Dict[str, Any] = Body(...)):
        """Erzeugt serverseitig ein PDF aus den vom Browser gesendeten Wizard-Daten."""
        pdf_bytes = build_contract_pdf(payload)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="mietvertrag.pdf"'},
        )

    app.include_router(router)
