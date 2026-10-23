"""Durable, user-bound read sessions. A claimed network step is never blindly retried."""
from __future__ import annotations

import hashlib
import hmac
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ..db.bank_models import FinTSSessionORM
from . import business_qol as commands
from .bank_imports import BankImports, StageImport
from .fints_adapter import PythonFinTSAdapter
from .integrations import connection_storage as records


class StartFinTS(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=1, max_length=128)
    account_id: str
    bank_code: str = Field(pattern=r'^\d{8}$')
    user_id: str = Field(min_length=1, max_length=128)
    pin: SecretStr
    server: str = Field(max_length=2048)
    product_id: str = Field(min_length=1, max_length=128)
    customer_id: str | None = None
    tan_mechanism: str | None = None
    tan_medium: str | None = None
    date_from: date
    date_to: date

    @model_validator(mode='after')
    def valid_range(self):
        if not self.pin.get_secret_value():
            raise ValueError('Bitte die Bank-PIN eingeben')
        url = urlsplit(self.server)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('Bankadresse muss eine HTTPS-Adresse ohne Zugangsdaten sein')
        if self.date_from > self.date_to:
            raise ValueError('Beginn liegt nach dem Ende')
        return self


class FinTSStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=1, max_length=128)
    base_revision: int = Field(ge=1)
    tan: SecretStr | None = None
    selected_account: int | None = Field(default=None, ge=0)


class CancelFinTS(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    base_revision: int = Field(ge=1)


class FinTS(BankImports):
    def __init__(self, store, box=None, adapter_factory=PythonFinTSAdapter):
        super().__init__(store, box)
        self.adapter_factory = adapter_factory

    def session(self, unit, identifier):
        row = records.row(unit, FinTSSessionORM, identifier, lock=bool(getattr(unit, 'bank_writer', False)))
        self.account(unit, row.account_id)
        if row.actor_id != unit.actor_id:
            raise HTTPException(404, 'Bankabruf nicht gefunden')
        return row

    def private(self, row):
        return self.open(row.private_token, f'fints-session/{row.id}')

    def view(self, row, private):
        state = private.get('protocol', {})
        expired = records.now() >= row.expires_at and row.state not in ('received', 'cancelled')
        return {'id': row.id, 'revision': row.revision, 'state': 'expired' if expired else row.state,
                'expires_at': records.stamp(row.expires_at), 'accounts': state.get('accounts', []),
                'challenge': state.get('challenge_text') if not expired else None,
                'decoupled': state.get('decoupled', False), 'challenge_image': state.get('challenge_image') if not expired else None,
                'challenge_hhduc': state.get('challenge_hhduc') if not expired else None,
                'imports': private.get('imports', []), 'error': private.get('error')}

    def get(self, identifier, actor_id):
        with self.work(actor_id) as unit:
            row = self.session(unit, identifier)
            return self.view(row, self.private(row))

    def receipt_view(self, row):
        # Bank-returned challenges and account lists belong only in the encrypted session.
        return {'id': row.id, 'revision': row.revision, 'state': row.state, 'expires_at': records.stamp(row.expires_at)}

    def start(self, payload: StartFinTS, actor_id):
        # Verify local dependency before storing credentials; construction does no I/O.
        self.adapter_factory()
        with self.work(actor_id, True) as unit:
            self.account(unit, payload.account_id, True)
            # SecretStr serialization deliberately excludes PIN; bind retries via keyed token below.
            command = payload.model_copy(update={'pin': SecretStr('redacted')})
            previous = commands.replay(unit, actor_id, 'fints-start', command)
            if previous:
                current_row = self.session(unit, previous['id'])
                old = self.private(current_row)
                verifier = hmac.new(old['salt'].encode(), payload.pin.get_secret_value().encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(old['pin_verifier'], verifier):
                    raise HTTPException(409, 'Diese Vorgangskennung wurde mit anderen Zugangsdaten verwendet')
                return {**self.view(current_row, old), 'replayed': True}
            identifier = str(uuid4())
            config = payload.model_dump(mode='json', exclude={'idempotency_key', 'account_id', 'pin'})
            config['pin'] = payload.pin.get_secret_value()
            private: dict[str, Any] = {'config': config, 'protocol': {'phase': 'init'}, 'salt': uuid4().hex}
            private['pin_verifier'] = hmac.new(private['salt'].encode(), config['pin'].encode(), hashlib.sha256).hexdigest()
            now = records.now()
            row = records.put(unit, FinTSSessionORM, {'id': identifier, 'actor_id': actor_id,
                'account_id': payload.account_id, 'state': 'ready', 'revision': 1, 'created_at': now,
                'expires_at': now + timedelta(minutes=10), 'private_token': self.seal(private, f'fints-session/{identifier}')})
            response = self.view(row, private)
            commands.save_command(unit, actor_id, 'fints-start', command,
                {'kind': 'account', 'entity_id': row.account_id, 'property_id': None}, self.receipt_view(row))
            return response

    def advance(self, identifier, payload: FinTSStep, actor_id):
        adapter = self.adapter_factory()
        with self.work(actor_id, True) as unit:
            row = self.session(unit, identifier)
            private = self.private(row)
            tan = payload.tan.get_secret_value() if payload.tan else None
            # Never journal a TAN or a dictionary-attackable unsalted TAN digest.
            tan_hash = hmac.new(private['salt'].encode(), (tan or '').encode(), hashlib.sha256).hexdigest()
            # Supply a sanitized command; the TAN itself never enters the journal.
            command = StageImport(idempotency_key=payload.idempotency_key, account_id=row.account_id,
                filename=identifier, source_base64=tan_hash, format='fints',
                options={'revision': payload.base_revision, 'selected': payload.selected_account})
            replay = commands.replay(unit, actor_id, 'fints-step/' + identifier, command)
            if replay:
                return {**self.view(row, private), 'replayed': True}
            if row.revision != payload.base_revision or row.state not in ('ready', 'tan_required', 'select_account'):
                raise HTTPException(409, 'Der Abrufstand wurde geändert oder dieser Schritt läuft bereits. Bitte neu laden')
            if row.expires_at <= records.now():
                raise HTTPException(409, 'Bankfreigabe abgelaufen. Bitte abbrechen und neu anmelden')
            if row.state == 'tan_required' and tan is None and not private['protocol'].get('decoupled'):
                raise HTTPException(422, 'Bitte die aktuelle TAN eingeben')
            if row.state == 'select_account':
                accounts = private['protocol']['accounts']
                if payload.selected_account is None or payload.selected_account >= len(accounts):
                    raise HTTPException(422, 'Bitte ein abgerufenes Bankkonto auswählen')
                local = self.account(unit, row.account_id)
                selected_iban = accounts[payload.selected_account][0]
                if not local.iban or local.iban.replace(' ', '').upper() != selected_iban.replace(' ', '').upper():
                    raise HTTPException(409, 'Das ausgewählte Bankkonto passt nicht zur gespeicherten IBAN des Zielkontos')
            data = records.values(row)
            data.update(state='running', revision=row.revision + 1)
            row = records.put(unit, FinTSSessionORM, data)
            claimed_revision, account_id = row.revision, row.account_id
            claim = commands.save_command(unit, actor_id, 'fints-step/' + identifier, command,
                {'kind': 'account', 'entity_id': account_id, 'property_id': None}, self.receipt_view(row))
            claim_revision = claim.updated_at.isoformat()
        # No DB/account locks during network waits. Any crash leaves a durable running state.
        try:
            result = adapter.step(private['config'], private['protocol'], tan=tan, selected=payload.selected_account)
            failure = None
        except Exception:
            result, failure = {}, 'Die Bank hat den Abruf nicht abgeschlossen. Bitte abbrechen und erneut anmelden; es wurden keine Zahlungen beauftragt.'
        with self.work(actor_id, True) as unit:
            row = self.session(unit, identifier)
            if row.revision != claimed_revision or row.state != 'running':
                raise HTTPException(409, 'Der Bankabruf wurde inzwischen abgebrochen. Die späte Antwort wird verworfen')
            private['protocol'] = result
            if failure:
                private['error'] = failure
            state = 'failed' if failure else result['state']
            # Retain received original bytes encrypted until separately staged; no network repeat needed.
            if state in ('received', 'failed'):
                private.pop('config', None)
            data = records.values(row)
            data.update(state=state, revision=row.revision + 1,
                        private_token=self.seal(private, f'fints-session/{identifier}'))
            row = records.put(unit, FinTSSessionORM, data)
            response = self.view(row, private)
            # The network claim is already durable. Advance that exact receipt;
            # never recreate/upsert it or erase a concurrent command's outcome.
            commands.advance_command(unit, actor_id, 'fints-step/' + identifier,
                command, claim_revision, self.receipt_view(row))
            return response

    def stage_received(self, identifier, payload: CancelFinTS, actor_id):
        with self.work(actor_id) as unit:
            row = self.session(unit, identifier)
            if row.revision != payload.base_revision:
                raise HTTPException(409, 'Bitte den aktuellen Abrufstand laden')
            if row.state != 'received':
                raise HTTPException(409, 'Es liegen keine abgeschlossenen Bankdaten vor')
            private = self.private(row)
            originals = private['protocol']['originals']
            formats = private['protocol'].get('formats', ['camt'] * len(originals))
            account_id = row.account_id
        imports = []
        for index, raw in enumerate(originals):
            preview = self.stage(StageImport(idempotency_key=f'fints/{identifier}/{index}', account_id=account_id,
                filename=f'Bankabruf-{identifier}-{index+1}.{ "xml" if formats[index] == "camt" else "sta" }', source_base64=raw,
                format=formats[index], options={'encoding': 'iso-8859-1'} if formats[index] == 'mt940' else {}), actor_id)
            imports.append(preview)
        return {'imports': imports}

    def cancel(self, identifier, payload: CancelFinTS, actor_id):
        with self.work(actor_id, True) as unit:
            row = self.session(unit, identifier)
            replay = commands.replay(unit, actor_id, 'fints-cancel/' + identifier, payload)
            if replay:
                return replay
            if row.revision != payload.base_revision:
                raise HTTPException(409, 'Bitte den aktuellen Abrufstand laden')
            old = self.private(row)
            private = {'salt': old['salt'], 'pin_verifier': old['pin_verifier'], 'protocol': {}}
            data = records.values(row)
            data.update(state='cancelled', revision=row.revision + 1,
                        private_token=self.seal(private, f'fints-session/{identifier}'))
            row = records.put(unit, FinTSSessionORM, data)
            response = self.view(row, private)
            commands.save_command(unit, actor_id, 'fints-cancel/' + identifier, payload,
                {'kind': 'account', 'entity_id': row.account_id, 'property_id': None}, response)
            return response
