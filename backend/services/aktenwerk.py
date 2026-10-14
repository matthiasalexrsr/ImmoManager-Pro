"""Document exchange with Aktenwerk, the document management system (DMS).

Contract ``immomanager-aktenwerk/1`` (docs/AKTENWERK_INTERFACE_20261014.md):

* Every document ImmoManager holds is an *entry* with a stable ``exchange_id``: archived documents
  (contracts, invoices, statements, protocols, letters) and the receipts attached to bookings.
* An entry carries the file (name, media type, size, SHA-256) and what ImmoManager knows about it:
  its kind, date, the property/unit/tenant/contract it belongs to, invoice and booking figures and
  the tax view (relevant for the rental income return, deductible as Werbungskosten).
* ``export_package`` writes ``manifest.json`` plus the files into a ZIP that Aktenwerk imports.
* ``send_entries`` hands entries to a configured Aktenwerk instance, one HTTP request per document,
  only on an explicit request; the idempotency key ``<exchange_id>:<sha256>`` lets Aktenwerk keep a
  document once however often it is sent.

Everything is read through the store of the current request, so the portfolio boundary of the
signed-in account applies to the manifest, the package and the transfer alike.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import mimetypes
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

SCHEMA = "immomanager-aktenwerk/1"
EXCHANGE_PREFIX = "immomanager"
API_PATH = "/api/immomanager/v1"

# document_type (free text of the documents page, or a key the program sets) -> exchange kind
_RAW_KINDS: dict[str, str] = {
    "mietvertrag": "vertrag", "vertrag": "vertrag", "kundigung": "vertrag", "versicherung": "vertrag",
    "rechnung": "rechnung", "handwerkerrechnung": "rechnung",
    "nebenkostenabrechnung": "abrechnung", "betriebskostenabrechnung": "abrechnung",
    "deposit_settlement": "abrechnung",
    "protokoll": "protokoll", "ubergabeprotokoll": "protokoll", "handover_protocol": "protokoll",
    "maintenance_protocol": "protokoll",
    "mahnung": "korrespondenz", "dunning_letter": "korrespondenz",
    "steuerbescheid": "bescheid", "grundbuchauszug": "nachweis", "energieausweis": "nachweis",
    "housing_confirmation": "bescheinigung",
    # short keys of imported and demo data, and keys the program uses internally
    "contract": "vertrag", "service_contract": "vertrag", "invoice": "rechnung", "beleg": "beleg", "receipt": "beleg",
    "kontoauszug": "beleg", "statement": "abrechnung", "bescheid": "bescheid", "genehmigung": "bescheid",
    "grundbuch": "nachweis", "teilungserklarung": "nachweis", "flurkarte": "nachweis", "bericht": "korrespondenz",
    "brief": "korrespondenz", "antrag": "korrespondenz", "letter": "korrespondenz",
}
KINDS = ("vertrag", "rechnung", "beleg", "abrechnung", "protokoll", "korrespondenz", "bescheid", "nachweis",
         "bescheinigung", "sonstiges")


def _fold(text: str | None) -> str:
    """Umlauts and their spellings alike: Übergabeprotokoll, Uebergabeprotokoll, ubergabeprotokoll."""
    value = (text or "").strip().lower()
    for umlaut, plain in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss"), ("ae", "a"), ("oe", "o"), ("ue", "u")):
        value = value.replace(umlaut, plain)
    return value


_KINDS = {_fold(key): kind for key, kind in _RAW_KINDS.items()}


def document_kind(document_type: str | None) -> str:
    return _KINDS.get(_fold(document_type), "sonstiges")


def _day(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10] if value else None


def _money(value: Any) -> str | None:
    """Amounts as decimal strings (cents), never as binary floats."""
    if value is None:
        return None
    return f"{round(float(value) * 100) / 100:.2f}"


@dataclass
class Entry:
    exchange_id: str
    kind: str
    title: str
    date: str | None
    file_url: str
    references: dict = field(default_factory=dict)
    finance: dict | None = None
    tax: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    source: dict = field(default_factory=dict)

    def as_manifest(self, file_info: dict | None = None) -> dict:
        data = {
            "exchange_id": self.exchange_id, "kind": self.kind, "title": self.title, "date": self.date,
            "references": self.references, "finance": self.finance, "tax": self.tax, "tags": self.tags,
            "source": self.source,
        }
        if file_info is not None:
            data["file"] = file_info
        return data


def _named(record: Any, name_field: str) -> dict | None:
    if record is None:
        return None
    return {"id": record.id, "name": getattr(record, name_field, None)}


def _references(lookup: dict, property_id=None, unit_id=None, tenant_id=None, contract_id=None) -> dict:
    refs = {
        "property": _named(lookup["properties"].get(property_id), "name"),
        "unit": _named(lookup["units"].get(unit_id), "label"),
        "tenant": _named(lookup["tenants"].get(tenant_id), "full_name"),
        "contract": _named(lookup["contracts"].get(contract_id), "contract_number"),
    }
    return {key: value for key, value in refs.items() if value}


def _lookup(store) -> dict:
    return {
        "properties": {p.id: p for p in store.list_properties()},
        "units": {u.id: u for u in store.list_units()},
        "tenants": {t.id: t for t in store.list_tenants()},
        "contracts": {c.id: c for c in store.list_contracts()},
        "categories": {c.id: c for c in store.list_categories()},
    }


def _tax_for_kind(kind: str, year: str | None) -> dict:
    """The rental income return's view (Anlage V); amounts are decided by the tax adviser, not here."""
    relevant = kind in ("rechnung", "beleg", "abrechnung", "bescheid")
    return {"relevant": relevant, "deductible": kind == "rechnung", "category": "werbungskosten" if kind == "rechnung"
            else ("nebenkosten" if kind == "abrechnung" else ("steuerbescheid" if kind == "bescheid" else None)),
            "year": int(year[:4]) if relevant and year else None}


def collect_entries(store) -> list[Entry]:
    """Every exchangeable document the current account may see, oldest first."""
    lookup = _lookup(store)
    invoices_by_document = {inv.source_document_id: inv for inv in store.list_invoices() if inv.source_document_id}
    entries: list[Entry] = []
    document_urls: set[str] = set()
    for doc in store.list_documents():
        if not doc.file_url:
            continue
        document_urls.add(doc.file_url)
        kind = document_kind(doc.document_type)
        invoice = invoices_by_document.get(doc.id)
        when = _day(doc.document_date) or (_day(invoice.invoice_date) if invoice else None)
        finance = None
        if invoice is not None:
            kind = "rechnung"
            finance = {"currency": "EUR", "gross": _money(invoice.gross_amount), "net": _money(invoice.net_amount),
                       "vat_rate": _money(invoice.vat_rate), "vat": _money(invoice.vat_amount),
                       "supplier": invoice.supplier, "invoice_date": _day(invoice.invoice_date),
                       "invoice_number": getattr(invoice, "invoice_number", None), "invoice_id": invoice.id}
        # a document filed under a contract belongs to its tenant, unit and property as well
        contract = lookup["contracts"].get(doc.contract_id)
        entries.append(Entry(
            exchange_id=f"{EXCHANGE_PREFIX}:document:{doc.id}", kind=kind, title=doc.title, date=when,
            file_url=doc.file_url,
            references=_references(lookup,
                                   doc.property_id or (invoice.property_id if invoice else None)
                                   or (contract.property_id if contract else None),
                                   doc.unit_id or (contract.unit_id if contract else None),
                                   doc.tenant_id or (contract.tenant_id if contract else None), doc.contract_id),
            finance=finance, tax=_tax_for_kind(kind, when),
            tags=[t.strip() for t in (doc.tags or "").split(",") if t.strip()],
            source={"type": "document", "id": doc.id, "document_type": doc.document_type},
        ))
    for booking in store.list_bookings():
        url = (booking.receipt_url or "").strip()
        if not url or url in document_urls:
            continue                          # no receipt, or the receipt is an archived document above
        when = _day(booking.booking_date)
        category = lookup["categories"].get(booking.category_id)
        amount = float(booking.amount)
        expense = amount < 0 and not booking.reverses_booking_id
        entries.append(Entry(
            exchange_id=f"{EXCHANGE_PREFIX}:booking-receipt:{booking.id}", kind="beleg",
            title=booking.payment_text or f"Beleg vom {when}", date=when, file_url=url,
            references=_references(lookup, booking.property_id, booking.unit_id, booking.tenant_id),
            finance={"currency": "EUR", "amount": _money(amount), "booking_id": booking.id,
                     "category": category.name if category else None,
                     "category_type": category.category_type if category else None},
            tax={"relevant": True, "deductible": expense, "category": "werbungskosten" if expense else "einnahmen",
                 "year": int(when[:4]) if when else None},
            source={"type": "booking", "id": booking.id},
        ))
    entries.sort(key=lambda e: (e.date or "", e.exchange_id))
    return entries


@dataclass
class Selection:
    kinds: set[str] | None = None
    year: int | None = None
    property_id: str | None = None
    tax_relevant: bool = False
    deductible: bool = False
    exchange_ids: set[str] | None = None

    def matches(self, entry: Entry) -> bool:
        if self.exchange_ids is not None and entry.exchange_id not in self.exchange_ids:
            return False
        if self.kinds and entry.kind not in self.kinds:
            return False
        if self.year and not (entry.date or "").startswith(f"{self.year:04d}"):
            return False
        if self.property_id and entry.references.get("property", {}).get("id") != self.property_id:
            return False
        if self.tax_relevant and not entry.tax.get("relevant"):
            return False
        if self.deductible and not entry.tax.get("deductible"):
            return False
        return True


def select(store, selection: Selection) -> list[Entry]:
    return [entry for entry in collect_entries(store) if selection.matches(entry)]


class FileUnavailable(Exception):
    """The file of an entry cannot be read (missing, outside the account's portfolios, not an upload)."""


def read_file(store, entry: Entry, actor_id: str) -> tuple[bytes, str]:
    """Bytes and file name of an entry, through the same checks as a download."""
    from fastapi import HTTPException

    from ..routers.files import _file_url_to_key
    from .file_storage import get_file_storage
    from .portfolio_scope import require_file_access
    from .upload_policy import ARCHIVED_PREFIXES, read_archived_pdf

    key = _file_url_to_key(entry.file_url)
    if not key:
        raise FileUnavailable("Die Dateiadresse verweist auf keine gespeicherte Datei.")
    try:
        if key.startswith(ARCHIVED_PREFIXES):
            data = read_archived_pdf(store, key, actor_id)   # the verified original
        else:
            require_file_access(key)
            data = get_file_storage().get(key)
    except HTTPException as exc:
        raise FileUnavailable(str(exc.detail)) from exc
    if data is None:
        raise FileUnavailable("Die Datei wurde nicht gefunden.")
    return data, key.rsplit("/", 1)[-1]


_UNSAFE = re.compile(r"[^0-9A-Za-zÄÖÜäöüß._ -]+")


def _safe_name(text: str, limit: int = 80) -> str:
    cleaned = _UNSAFE.sub("_", text or "").strip(" ._") or "dokument"
    return cleaned[:limit]


def file_info(data: bytes, original_name: str, entry: Entry) -> dict:
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
    media_type = mimetypes.types_map.get(f".{extension}", "application/octet-stream")
    short = hashlib.sha256(entry.exchange_id.encode()).hexdigest()[:8]
    year = (entry.date or "ohne-datum")[:4]
    return {
        "name": f"{_safe_name(entry.title)}__{short}.{extension}",
        "path": f"files/{entry.kind}/{year}/{_safe_name(entry.title)}__{short}.{extension}",
        "media_type": media_type, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }


def manifest(entries: Iterable[Entry], *, files: dict[str, dict] | None = None, problems: list[dict] | None = None,
             app_version: str | None = None) -> dict:
    return {
        "schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"system": "ImmoManager Pro", "version": app_version},
        "entries": [entry.as_manifest(files.get(entry.exchange_id) if files is not None else None) for entry in entries
                    if files is None or entry.exchange_id in files],
        "problems": problems or [],
    }


def export_package(store, entries: list[Entry], actor_id: str, app_version: str | None = None) -> tuple[bytes, dict]:
    """ZIP with manifest.json and every readable file; unreadable entries are listed under problems."""
    files: dict[str, dict] = {}
    problems: list[dict] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            try:
                data, name = read_file(store, entry, actor_id)
            except FileUnavailable as exc:
                problems.append({"exchange_id": entry.exchange_id, "title": entry.title, "reason": str(exc)})
                continue
            info = file_info(data, name, entry)
            files[entry.exchange_id] = info
            archive.writestr(info["path"], data)
        document = manifest(entries, files=files, problems=problems, app_version=app_version)
        archive.writestr("manifest.json", json.dumps(document, ensure_ascii=False, indent=2))
    return buffer.getvalue(), document


# --- Transfer to a running Aktenwerk instance -----------------------------------------------------

_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".fritz.box")


def base_url_problem(value: str) -> str | None:
    """None for a usable base URL; plain HTTP only inside the local network."""
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "Adresse muss mit http:// oder https:// beginnen und einen Rechnernamen enthalten"
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return "Adresse ohne Zugangsdaten, Abfrage oder Sprungmarke angeben (Token separat)"
    if parsed.scheme == "http":
        host = parsed.hostname
        try:
            address = ipaddress.ip_address(host)
            local = address.is_loopback or address.is_private or address.is_link_local
        except ValueError:
            local = host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES)
        if not local:
            return "Außerhalb des lokalen Netzes ist HTTPS nötig, damit Dokumente und Token verschlüsselt übertragen werden"
    return None


def _endpoint(config: dict, path: str) -> str:
    return config["base_url"].strip().rstrip("/") + API_PATH + path


def _headers(config: dict) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "ImmoManager-Pro"}
    if config.get("api_token"):
        headers["Authorization"] = f"Bearer {config['api_token']}"
    return headers


def check_connection(config: dict, client=None) -> tuple[bool, str]:
    import httpx

    owns = client is None
    client = client or httpx.Client(timeout=float(config.get("timeout") or 15), verify=config.get("verify_tls", True))
    try:
        response = client.get(_endpoint(config, "/health"), headers=_headers(config))
    except httpx.HTTPError as exc:
        return False, f"Aktenwerk nicht erreichbar ({type(exc).__name__}). Adresse und Netzwerk prüfen."
    finally:
        if owns:
            client.close()
    if response.status_code in (401, 403):
        return False, "Aktenwerk hat den Zugang abgelehnt. Token prüfen."
    if response.status_code != 200:
        return False, f"Aktenwerk antwortete mit HTTP {response.status_code}."
    return True, "Verbindung zu Aktenwerk geprüft; nichts übertragen."


def send_entries(store, entries: list[Entry], config: dict, actor_id: str, client=None) -> dict:
    """POST each document to Aktenwerk; results per entry, a failure does not stop the others."""
    import httpx

    owns = client is None
    client = client or httpx.Client(timeout=float(config.get("timeout") or 30), verify=config.get("verify_tls", True))
    results: list[dict[str, Any]] = []
    try:
        for entry in entries:
            try:
                data, name = read_file(store, entry, actor_id)
            except FileUnavailable as exc:
                results.append({"exchange_id": entry.exchange_id, "title": entry.title, "status": "failed", "reason": str(exc)})
                continue
            info = file_info(data, name, entry)
            metadata = {"schema": SCHEMA, **entry.as_manifest(info)}
            try:
                response = client.post(
                    _endpoint(config, "/documents"),
                    headers={**_headers(config), "Idempotency-Key": f"{entry.exchange_id}:{info['sha256']}"},
                    data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                    files={"file": (info["name"], data, info["media_type"])},
                )
            except httpx.HTTPError as exc:
                results.append({"exchange_id": entry.exchange_id, "title": entry.title, "status": "failed",
                                "reason": f"Aktenwerk nicht erreichbar ({type(exc).__name__})"})
                continue
            if response.status_code in (200, 201, 409):
                # 409: Aktenwerk already holds exactly this file under this exchange id
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                results.append({"exchange_id": entry.exchange_id, "title": entry.title,
                                "status": "already_present" if response.status_code == 409 else "sent",
                                "aktenwerk_id": body.get("id") if isinstance(body, dict) else None,
                                "sha256": info["sha256"]})
            else:
                reason = {401: "Zugang abgelehnt (Token prüfen)", 403: "Zugang abgelehnt (Token prüfen)",
                          413: "Datei zu groß für Aktenwerk", 415: "Dateityp von Aktenwerk nicht angenommen",
                          422: "Metadaten von Aktenwerk nicht angenommen"}.get(response.status_code,
                                                                              f"HTTP {response.status_code}")
                results.append({"exchange_id": entry.exchange_id, "title": entry.title, "status": "failed", "reason": reason})
    finally:
        if owns:
            client.close()
    sent = sum(1 for r in results if r["status"] in ("sent", "already_present"))
    return {"sent": sent, "failed": len(results) - sent, "results": results}
