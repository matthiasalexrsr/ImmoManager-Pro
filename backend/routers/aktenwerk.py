"""Documents for Aktenwerk (DMS): manifest, export package and the explicit hand-over."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import aktenwerk as exchange
from ..services.integrations.base import IntegrationActionResult
from ..services.integrations.manager import integration_manager

router = APIRouter(prefix="/aktenwerk", tags=["Aktenwerk"])

MAX_SEND = 200


def _app_version() -> str | None:
    try:
        from ..config import settings

        return getattr(settings, "app_version", None)
    except Exception:  # pragma: no cover - the version is informative only
        return None


def _selection(kind: list[str] | None, year: int | None, property_id: str | None, tax_relevant: bool,
               deductible: bool, exchange_ids: list[str] | None = None) -> exchange.Selection:
    unknown = [k for k in (kind or []) if k not in exchange.KINDS]
    if unknown:
        raise HTTPException(422, f"Unbekannte Dokumentart: {', '.join(unknown)}")
    return exchange.Selection(kinds=set(kind) if kind else None, year=year, property_id=property_id,
                              tax_relevant=tax_relevant, deductible=deductible,
                              exchange_ids=set(exchange_ids) if exchange_ids is not None else None)


Kinds = Annotated[list[str] | None, Query(description="Dokumentarten, z. B. rechnung, beleg, vertrag")]


@router.get("/status")
def get_status() -> dict:
    """Whether a hand-over can start (switched on, address set): for the "An Aktenwerk" buttons.

    Open to every signed-in account, including one limited to some portfolios; the settings
    themselves (/integrations/aktenwerk) stay with the installation's administrators.
    """
    return integration_manager.readiness("aktenwerk")


@router.get("/manifest")
def get_manifest(
    kind: Kinds = None,
    year: Annotated[int | None, Query(ge=1900, le=2999)] = None,
    property_id: str | None = None,
    tax_relevant: bool = False,
    deductible: bool = False,
) -> dict:
    """What an export would contain (without reading the files): for the preview and for a pulling DMS."""
    entries = exchange.select(store, _selection(kind, year, property_id, tax_relevant, deductible))
    document = exchange.manifest(entries, app_version=_app_version(), stamped=False)
    document["counts"] = {k: sum(1 for e in entries if e.kind == k) for k in exchange.KINDS
                          if any(e.kind == k for e in entries)}
    return document


@router.get("/export")
def export(
    actor: Annotated[UserRead, Depends(require_auth)],
    kind: Kinds = None,
    year: Annotated[int | None, Query(ge=1900, le=2999)] = None,
    property_id: str | None = None,
    tax_relevant: bool = False,
    deductible: bool = False,
) -> Response:
    """ZIP with manifest.json and the files, for an import into Aktenwerk (no connection needed)."""
    entries = exchange.select(store, _selection(kind, year, property_id, tax_relevant, deductible))
    if not entries:
        raise HTTPException(404, "Für diese Auswahl gibt es keine Dokumente.")
    data, _ = exchange.export_package(store, entries, actor.id, _app_version())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    suffix = f"-{year}" if year else ""
    return Response(content=data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="aktenwerk-export{suffix}-{stamp}.zip"',
        "X-Content-Type-Options": "nosniff",
    })


class SendRequest(BaseModel):
    exchange_ids: list[str] = Field(min_length=1, max_length=MAX_SEND)


@router.post("/send")
def send(payload: SendRequest, actor: Annotated[UserRead, Depends(require_auth)]) -> dict:
    """Hand the chosen documents to the configured Aktenwerk; only on this explicit request."""
    wanted = list(dict.fromkeys(payload.exchange_ids))
    entries, aliases = exchange.select_for_transfer(store, wanted)
    missing = [exchange_id for exchange_id in wanted if exchange_id not in aliases]
    outcome: dict = {}

    def work(config: dict) -> IntegrationActionResult:
        outcome.update(exchange.send_entries(store, entries, config, actor.id))
        by_id = {item["exchange_id"]: item for item in outcome["results"]}
        results = [{**by_id[aliases[requested]], "exchange_id": requested,
                    **({"canonical_exchange_id": aliases[requested]} if aliases[requested] != requested else {})}
                   for requested in wanted if requested in aliases]
        results += [{"exchange_id": exchange_id, "status": "failed",
                                         "reason": "Dokument nicht gefunden oder nicht sichtbar"} for exchange_id in missing]
        outcome["results"] = results
        outcome["sent"] = sum(item["status"] in ("sent", "already_present") for item in results)
        outcome["failed"] = len(results) - outcome["sent"]
        sent, failed = outcome["sent"], outcome["failed"]
        message = (f"{sent} an Aktenwerk übergeben" + (f", {failed} fehlgeschlagen" if failed else "")) if sent \
            else "Nichts übergeben" + (f" ({failed} fehlgeschlagen)" if failed else "")
        # the journal keeps which documents went where, not their content
        return IntegrationActionResult(success=failed == 0 and sent > 0, message=message,
                                       details={"sent": sent, "failed": failed,
                                                "results": [{k: v for k, v in r.items() if k != "title"} for r in results]})

    result = integration_manager.execute("aktenwerk", {"action": "send_documents", "exchange_ids": wanted,
                                                       "count": len(wanted)}, work, journal_all_keys=True)
    if not outcome:
        # disabled, not configured, or the journal is unavailable: nothing was sent
        raise HTTPException(409, result.get("message") or "Aktenwerk ist nicht bereit.")
    return {"message": result["message"], "sent": outcome["sent"], "failed": outcome["failed"],
            "results": outcome["results"], **({"history_warning": result["history_warning"]}
                                             if result.get("history_warning") else {})}
