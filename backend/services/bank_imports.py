"""Controlled receive → complete staged preview → explicit atomic publication."""
from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from .. import auth
from ..db.bank_models import BankImportORM, BankSourceLinkORM
from ..db.orm_models import AccountORM
from ..models import BookingCreate
from ..storage import NotFoundError
from . import business_qol as commands
from .bank_formats import BankFormatError, parse
from .booking_writes import booking_write
from .document_versions import Unit, check_account, memory_archive
from .integrations import connection_storage as records
from .portfolio_scope import scope_context, scope_from_user
from .secret_box import SecretError, default_secret_box
from .workspace_contexts import bound_actor


def protect_bank_booking(store, booking_id, changes=None):
    """Assignment may change; the imported bank event itself remains an original."""
    if hasattr(store, 'db'):
        present = store.db.scalar(select(BankSourceLinkORM.id).where(BankSourceLinkORM.booking_id == booking_id).limit(1))
    else:
        present = any(r.booking_id == booking_id for r in store.__dict__.get('_integration_connections', {}).get('bank_source_links', {}).values())
    if not present:
        return
    if changes is None:
        raise HTTPException(409, 'Importierte Bankbewegungen bleiben als Quellnachweis erhalten. Bitte eine separate Korrektur buchen')
    original = store.get_booking(booking_id).model_dump(mode='json')
    for name in ('account_id', 'booking_date', 'amount', 'payment_text', 'receipt_url', 'reverses_booking_id'):
        if name in changes:
            value = changes[name].isoformat() if hasattr(changes[name], 'isoformat') else changes[name]
            if value != original[name]:
                raise HTTPException(409, 'Die Originalangaben einer importierten Bankbewegung dürfen nicht geändert werden. Zuordnungen bleiben bearbeitbar')


class StageImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    account_id: str
    filename: str = Field(min_length=1, max_length=255)
    source_base64: str = Field(max_length=70_000_000)
    format: str
    options: dict = Field(default_factory=dict)


class ConfirmImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    base_revision: int = Field(ge=1)
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: bool
    duplicate_decisions: dict[str, str] = Field(default_factory=dict)


def digest(value):
    return hashlib.sha256(records.canonical(value, enforce_budget=False)).hexdigest()


def usable_reference(value):
    return bool(value and value.strip().upper() not in ('NONREF', 'NOTPROVIDED', 'NOT PROVIDED', '0'))


class BankImports:
    def __init__(self, store, box=None):
        self.store, self.box = store, box or default_secret_box()

    def seal(self, value, context):
        try:
            return self.box.seal(json.dumps(value, ensure_ascii=False, allow_nan=False), context)
        except (SecretError, OSError):
            raise HTTPException(503, "Bankdaten konnten nicht sicher verschlüsselt werden") from None

    def open(self, value, context):
        try:
            return json.loads(self.box.open(value, context))
        except (SecretError, OSError, ValueError):
            raise HTTPException(503, "Bankdaten sind nicht lesbar. Bitte Schlüssel aus dem Vollbackup prüfen") from None

    @contextmanager
    def work(self, actor_id, write=False, *, booking_id=None, changes=None):
        try:
            with self._work(actor_id, write, booking_id=booking_id, changes=changes) as unit:
                yield unit
        except SQLAlchemyError:
            raise HTTPException(503, 'Bankdaten konnten nicht sicher gespeichert oder gelesen werden. Bitte denselben Schritt erneut versuchen') from None

    @contextmanager
    def _work(self, actor_id, write=False, *, booking_id=None, changes=None):
        user = check_account(auth.get_user_by_id(actor_id), write_areas=("/bookings",) if write else ())
        if user.get("role") not in ("eigentuemer", "verwalter", "buchhaltung", "techniker", "readonly"):
            raise HTTPException(403, "Bankimporte sind nur für interne Mitarbeiter freigegeben")
        with bound_actor(user), scope_context(scope_from_user(user)):
            if write:
                unit = None
                try:
                    with booking_write(self.store, booking_id=booking_id, changes=changes) as target:
                        db = target.db if hasattr(target, "db") else None
                        unit = Unit(target, db, user, memory_archive(target) if db is None else None)
                        setattr(unit, 'bank_writer', True)
                        yield unit
                except BaseException:
                    if unit is not None:
                        unit.rollback()
                    raise
            else:
                yield Unit(self.store, self.store.db if hasattr(self.store, "db") else None, user, None)
                current = check_account(auth.get_user_by_id(actor_id))
                if scope_from_user(current) != scope_from_user(user):
                    raise HTTPException(403, 'Berechtigungen wurden geändert. Bitte neu laden')

    def account(self, unit, account_id, lock=False):
        try:
            account = unit.store.get_account(account_id)
        except NotFoundError:
            raise HTTPException(404, "Bankkonto nicht gefunden oder nicht freigegeben") from None
        if lock and unit.db is not None:
            unit.db.scalar(select(AccountORM).where(AccountORM.id == account_id).with_for_update())
            unit.db.expire_all()
            account = unit.store.get_account(account_id)
        return account

    def currency(self, unit, account):
        if unit.store.get_portfolio(account.portfolio_id).currency != 'EUR':
            raise HTTPException(409, 'Die Bankdatei enthält EUR-Beträge. Das Zielkonto gehört zu einem '
                                'Portfolio mit anderer Währung; eine Umrechnung wird nicht erfunden')

    def source(self, unit, identifier):
        source = records.row(unit, BankImportORM, identifier, lock=bool(getattr(unit, 'bank_writer', False)))
        self.account(unit, source.account_id)
        return source

    def manifest(self, source):
        value = self.open(source.manifest_token, f"bank-manifest/{source.id}")
        if digest(value["preview"]) != value["preview_sha256"]:
            raise HTTPException(409, "Die gespeicherte Vorschau ist beschädigt")
        return value

    def summary(self, source, manifest):
        preview = manifest["preview"]
        statements = preview['metadata'].get('statements', [])
        balance_verified = bool(statements) and all(
            'opening_cents' in statement or {'OPBD', 'CLBD'}.issubset(statement.get('balances', {}))
            for statement in statements) and not preview['errors']
        return {"id": source.id, "account_id": source.account_id, "state": source.state,
                "revision": source.revision, "source_sha256": source.source_sha256,
                "preview_sha256": manifest["preview_sha256"], "filename": manifest["filename"],
                "format": preview["format"], "options": preview["options"], "row_count": len(preview["rows"]),
                "source_provenance": preview['options'].get('source_provenance', 'original_file'),
                "error_count": len(preview["errors"]), "total_cents": preview["total_cents"],
                "balance_verified": balance_verified,
                "receipt": ({key: manifest["receipt"][key] for key in ("created", "duplicates")}
                            if manifest.get("receipt") else None)}

    def stage(self, payload: StageImport, actor_id):
        try:
            raw = base64.b64decode(payload.source_base64, validate=True)
        except ValueError:
            raise HTTPException(422, "Ungültige Dateiübertragung") from None
        if not raw or len(raw) > 50 * 1024 * 1024:
            raise HTTPException(413, "Bitte eine Bankdatei bis 50 MiB auswählen")
        source_hash = hashlib.sha256(raw).hexdigest()
        mapping_hash = digest({"format": payload.format, "options": payload.options})
        try:
            parsed = parse(raw, payload.format, payload.options)
        except BankFormatError as exc:
            parsed = {"rows": [], "errors": [{"line": 0, "error": str(exc), "raw": ""}], "metadata": {}, "total_cents": 0}
        preview = {**parsed, "format": payload.format, "options": payload.options}
        references = Counter(row['reference'] for row in parsed['rows'] if usable_reference(row['reference']))
        for reference, count in references.items():
            if count > 1:
                parsed['errors'].append({'line': 0, 'error': 'Dieselbe eindeutige Bankreferenz kommt im Original mehrfach vor. Bitte die Quelle prüfen', 'raw': reference})
        with self.work(actor_id, True) as unit:
            account = self.account(unit, payload.account_id, True)
            self.currency(unit, account)
            for statement in parsed['metadata'].get('statements', []):
                iban = statement.get('iban')
                if iban and (not account.iban or iban.replace(' ', '').upper() != account.iban.replace(' ', '').upper()):
                    raise HTTPException(409, 'Das Bankoriginal gehört nicht zur gespeicherten IBAN des Zielkontos')
            previous = commands.replay(unit, actor_id, "bank-stage", payload)
            if previous:
                return previous
            existing = records.find_one(unit, BankImportORM, account_id=account.id,
                                        source_sha256=source_hash, mapping_sha256=mapping_hash)
            if existing:
                response = self.summary(existing, self.manifest(existing))
            else:
                identifier = str(uuid4())
                manifest = {"filename": payload.filename, "preview": preview, "preview_sha256": digest(preview)}
                source = records.put(unit, BankImportORM, {"id": identifier, "account_id": account.id, "actor_id": actor_id,
                    "source_sha256": source_hash, "mapping_sha256": mapping_hash,
                    "original_token": self.seal(payload.source_base64, f"bank-original/{identifier}"),
                    "manifest_token": self.seal(manifest, f"bank-manifest/{identifier}"),
                    "state": "invalid" if parsed["errors"] else "staged", "revision": 1, "created_at": records.now()})
                response = self.summary(source, manifest)
            commands.save_command(unit, actor_id, "bank-stage", payload,
                {"kind": "account", "entity_id": account.id, "property_id": None}, response)
            return response

    def preview(self, identifier, actor_id, offset=0, limit=100):
        if offset < 0 or not 1 <= limit <= 250:
            raise HTTPException(422, "Ungültiger Vorschauabschnitt")
        with self.work(actor_id) as unit:
            source = self.source(unit, identifier)
            manifest = self.manifest(source)
            preview = manifest["preview"]
            rows = []
            occurrences: Counter[str] = Counter()
            identities = {}
            for index, item in enumerate(preview['rows'][:offset+limit]):
                content_hash = digest({key: item[key] for key in ('date', 'cents', 'currency', 'text', 'reference')})
                occurrences[content_hash] += 1
                identities[index] = digest([source.account_id, 'reference', item['reference']] if usable_reference(item['reference'])
                    else [source.account_id, 'content', content_hash, occurrences[content_hash]])
            for index, item in enumerate(preview['rows'][offset:offset+limit], offset):
                semantic_hash = digest({key: item[key] for key in ('date', 'cents', 'currency', 'text')})
                known = records.row(unit, BankSourceLinkORM, identities[index], required=False)
                rows.append({**item, 'index': index, 'known_duplicate': bool(known),
                    'duplicate_candidates': [] if known else self.similar(unit, source.account_id, semantic_hash, source.id)})
            # Errors have their own full pagination, independent of successful rows.
            return {**self.summary(source, manifest), "rows": rows,
                    "errors": preview["errors"][offset:offset+limit], "offset": offset,
                    "links": manifest.get("receipt", {}).get("links", [])[offset:offset+limit],
                    "next_offset": offset + limit if offset + limit < max(len(preview["rows"]), len(preview["errors"])) else None}

    def list(self, account_id, actor_id, cursor=None, limit=50):
        if not 1 <= limit <= 250:
            raise HTTPException(422, 'Ungültige Seitengröße')
        namespace = ['bank-imports-v1', actor_id, account_id]
        after = commands.cursor_decode(cursor, namespace)
        try:
            if after and (len(after) != 2 or not all(isinstance(v, str) for v in after)):
                raise ValueError
            boundary = (datetime.fromisoformat(after[0]), after[1]) if after else None
            if boundary and boundary[0].tzinfo is not None:
                raise ValueError
        except ValueError:
            raise HTTPException(422, 'Ungültige Fortsetzung') from None
        with self.work(actor_id) as unit:
            self.account(unit, account_id)
            if unit.db is None:
                rows = sorted((r for r in records.memory(unit, BankImportORM).values() if r.account_id == account_id
                    and (not boundary or (r.created_at, r.id) > boundary)), key=lambda r: (r.created_at, r.id))[:limit+1]
            else:
                query = select(BankImportORM).where(BankImportORM.account_id == account_id)
                if boundary:
                    query = query.where(or_(BankImportORM.created_at > boundary[0],
                        and_(BankImportORM.created_at == boundary[0], BankImportORM.id > boundary[1])))
                rows = list(unit.db.scalars(query.order_by(BankImportORM.created_at, BankImportORM.id).limit(limit+1)))
            items = [{'id': r.id, 'state': r.state, 'revision': r.revision, 'source_sha256': r.source_sha256,
                      'created_at': r.created_at.isoformat()} for r in rows[:limit]]
            return {'items': items, 'has_more': len(rows) > limit,
                    'next_cursor': commands.cursor_encode(namespace, [items[-1]['created_at'], items[-1]['id']]) if len(rows) > limit else None}

    def original(self, identifier, actor_id):
        with self.work(actor_id) as unit:
            source = self.source(unit, identifier)
            raw = base64.b64decode(self.open(source.original_token, f"bank-original/{identifier}"), validate=True)
            if hashlib.sha256(raw).hexdigest() != source.source_sha256:
                raise HTTPException(409, "Originalhash stimmt nicht überein")
            return raw

    def similar(self, unit, account_id, semantic_hash, import_id):
        if unit.db is None:
            if not hasattr(unit, '_bank_similarity'):
                index: dict[tuple[str, str], list] = {}
                for link in records.memory(unit, BankSourceLinkORM).values():
                    index.setdefault((link.account_id, link.semantic_sha256), []).append(link)
                unit._bank_similarity = index
            matches = [r for r in unit._bank_similarity.get((account_id, semantic_hash), []) if r.import_id != import_id]
        else:
            matches = unit.db.scalars(select(BankSourceLinkORM).where(
                BankSourceLinkORM.account_id == account_id, BankSourceLinkORM.semantic_sha256 == semantic_hash,
                BankSourceLinkORM.import_id != import_id)).all()
        return sorted({r.booking_id for r in matches})

    def confirm(self, identifier, payload: ConfirmImport, actor_id):
        with self.work(actor_id, True) as unit:
            source = self.source(unit, identifier)
            account = self.account(unit, source.account_id, True)
            self.currency(unit, account)
            previous = commands.replay(unit, actor_id, "bank-confirm/" + identifier, payload)
            if previous:
                return previous
            manifest = self.manifest(source)
            if not payload.confirm or source.revision != payload.base_revision or payload.preview_sha256 != manifest["preview_sha256"]:
                raise HTTPException(409, "Bitte die aktuelle vollständige Vorschau prüfen und ausdrücklich bestätigen")
            if source.state != "staged" or manifest["preview"]["errors"]:
                raise HTTPException(409, "Dieser Import ist bereits bestätigt oder enthält Fehler")
            # Same original under a changed mapping must not silently create another ledger event.
            if unit.db is None:
                siblings = records.memory(unit, BankImportORM).values()
            else:
                siblings = unit.db.scalars(select(BankImportORM).where(BankImportORM.account_id == source.account_id,
                                                                      BankImportORM.source_sha256 == source.source_sha256)).all()
            if any(s.id != source.id and s.source_sha256 == source.source_sha256 and s.account_id == source.account_id and s.state == "confirmed" for s in siblings):
                raise HTTPException(409, "Dieses Original wurde bereits mit einer anderen Zuordnung übernommen")
            occurrences: Counter[str] = Counter()
            links = []
            if set(payload.duplicate_decisions) - {str(i) for i in range(len(manifest['preview']['rows']))}:
                raise HTTPException(422, 'Eine Dublettenentscheidung bezieht sich auf eine unbekannte Vorschauzeile')
            created = duplicate = 0
            for index, row in enumerate(manifest["preview"]["rows"]):
                content = {key: row[key] for key in ("date", "cents", "currency", "text", "reference")}
                content_hash = digest(content)
                semantic_hash = digest({key: value for key, value in content.items() if key != 'reference'})
                occurrences[content_hash] += 1
                reference = row["reference"]
                identity = [source.account_id, "reference", reference] if usable_reference(reference) else [source.account_id, "content", content_hash, occurrences[content_hash]]
                link_id = digest(identity)
                existing = records.row(unit, BankSourceLinkORM, link_id, required=False)
                if existing:
                    if existing.content_sha256 != content_hash:
                        raise HTTPException(409, "Eine bekannte Bankreferenz enthält geänderte Angaben. Bitte manuell prüfen")
                    booking_id = existing.booking_id
                    duplicate += 1
                else:
                    candidates = self.similar(unit, source.account_id, semantic_hash, source.id)
                    decision = payload.duplicate_decisions.get(str(index))
                    if candidates and decision not in [*candidates, 'new']:
                        raise HTTPException(409, 'Eine ähnliche Bankbewegung hat eine andere Referenz. Bitte in der Vorschau ausdrücklich als dieselbe oder neue Bewegung kennzeichnen')
                    if decision and decision != 'new' and decision not in candidates:
                        raise HTTPException(409, 'Die Dublettenentscheidung passt nicht zum aktuellen Bankbestand')
                    if decision in candidates:
                        booking_id = decision
                        duplicate += 1
                    else:
                        booking = unit.store.create_booking(BookingCreate(account_id=source.account_id, booking_date=row["date"],
                            amount=row["cents"] / 100, payment_text=row["text"], receipt_url=f"/api/v1/bank-imports/{identifier}/original"))
                        booking_id = booking.id
                        created += 1
                    records.put(unit, BankSourceLinkORM, {"id": link_id, "account_id": source.account_id,
                        "import_id": source.id, "booking_id": booking_id, "content_sha256": content_hash,
                        "semantic_sha256": semantic_hash, "created_at": records.now()})
                links.append({"line": row["line"], "booking_id": booking_id})
            receipt = {"created": created, "duplicates": duplicate, "links": links}
            manifest["receipt"] = receipt
            data = records.values(source)
            data.update(state="confirmed", revision=source.revision + 1,
                        manifest_token=self.seal(manifest, f"bank-manifest/{identifier}"))
            source = records.put(unit, BankImportORM, data)
            response = self.summary(source, manifest)
            # Large row links remain in the paginated receipt, not the command journal.
            response["receipt"] = {"created": created, "duplicates": duplicate}
            commands.save_command(unit, actor_id, "bank-confirm/" + identifier, payload,
                {"kind": "account", "entity_id": source.account_id, "property_id": None}, response)
            return response
