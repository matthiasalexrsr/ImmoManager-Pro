"""Explicit new-draft defaults and a collision-safe internal contract number allocator.

Defaults never patch existing financial rows. Supplier invoice numbers, insurance
policies and supplier contract numbers are external facts and are NOT allocated.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..db.daily_models import NumberReservationORM, SettingRuleORM
from ..db.orm_models import ContractORM
from . import daily_state as state
from . import document_versions as archive
from . import settings_catalogue as catalogue
from . import workspace_contexts as contexts
from .portfolio_scope import scope_context, scope_from_user

CONTEXTS = {'contracts': '/contracts', 'bookings': '/bookings', 'invoice-review': '/invoice-review/receipts',
            'housing-confirmation': '/documents'}


def connection_selection(unit, identifier):
    """Reference the current authority; never duplicate/decrypt its configuration."""
    from ..db.integration_connection_models import IntegrationConnectionORM
    from .integrations import connection_storage
    if not catalogue.setting_allowed(unit, 'preferred_connection'):
        raise HTTPException(403, 'Verbindungsauswahl benötigt aktuelle Installationsrechte.')
    row = connection_storage.row(unit, IntegrationConnectionORM, identifier)
    if row.archived:
        raise HTTPException(409, 'Die gewählte Verbindung ist archiviert.')
    return {'connection_id': row.id, 'config_revision': row.revision, 'provider_id': row.provider_id,
            'name': row.name, 'enabled': row.enabled}


def bank_import_profile(store, actor_id):
    """Exact StageImport format/options hook for the bank package. No receive/write."""
    with archive.work(store, actor_id) as unit:
        if not catalogue.setting_allowed(unit, 'bank_import_format'):
            raise HTTPException(403, 'Keine Berechtigung für Bankimporte.')
        values = {key: catalogue.effective(unit, key)[0] for key in catalogue.DEFAULTS if key.startswith('bank_')}
        return {'format': values['bank_import_format'], 'options': {
            'encoding': values['bank_csv_encoding'], 'delimiter': values['bank_csv_delimiter'],
            'decimal': values['bank_csv_decimal'], 'date_format': values['bank_csv_date_format'],
            'columns': {'date': values['bank_csv_date_column'], 'amount': values['bank_csv_amount_column'], 'text': values['bank_csv_text_column']}},
            'revision': state.get(unit, 'preferences')['revision']}


def selected_connection(store, actor_id):
    with archive.work(store, actor_id) as unit:
        identifier = catalogue.effective(unit, 'preferred_connection')[0]
        return connection_selection(unit, identifier) if identifier else None


def configuration_contract(store, actor_id):
    with archive.work(store, actor_id) as unit:
        if not catalogue.setting_allowed(unit, 'preferred_connection'):
            raise HTTPException(403, 'API- und Pluginverwaltung benötigt Installationsrechte.')
        from ..plugins import get_plugins
        return {'api': {'base': '/api/v1', 'schema': '/openapi.json',
                        'authorization': 'Aktuelle Rolle und Objektgrants; keine zusätzlichen Pluginrechte.',
                        'commands': 'Neue Einstellungen: erwartete Revision und Idempotenzschlüssel. Alte Preferences: APIv1-Teilupdate, zusätzliche Antwortfelder bleiben additiv.',
                        'secret_policy': 'Keine Geheimniswerte in dieser Ansicht. Verbindungsdaten ausschließlich über ihre bestehende geschützte Verwaltung.'},
                'plugins': [plugin.to_dict() for plugin in get_plugins()],
                'plugin_policy': 'Geladene Pythonplugins laufen mit Prozessrechten. Hier werden weder Installation noch Upgrade ausgelöst.',
                'hooks': ['setting_consumers.bank_import_profile', 'setting_consumers.selected_connection',
                          'setting_consumers.preview/apply', 'settings_catalogue.email_selection',
                          'notification_email.preview / Communication.check_outbound'],
                'notification_email_policy': 'Persönliche Hinweise: Vorschau und einzelne ausdrückliche Freigabe im bestehenden E-Mail-Ausgang; keine automatische Planung beim Ändern einer Einstellung. Aktuelle Kanalwahl, Ruhezeiten, Empfängeradresse und Quellrechte werden vor DATA erneut geprüft.'}


def _preview(unit, context, property_id):
    if context not in CONTEXTS:
        raise HTTPException(422, 'Für diesen Entwurf gibt es keine Fachvorgaben.')
    from ..permissions import may_write
    if not may_write(unit.user['role'], CONTEXTS[context]):
        raise HTTPException(403, 'Keine Berechtigung für diesen neuen Entwurf.')
    if property_id:
        contexts.resolve_context(unit.store, 'property', property_id, unit.actor_id)
    effective = {key: catalogue.effective(unit, key, property_id)[0] for key in catalogue.DEFAULTS}
    values = {}
    if context == 'bookings' and effective['confirmed_cost_defaults'] and effective['booking_category']:
        contexts.resolve_context(unit.store, 'category', effective['booking_category'], unit.actor_id)
        values['category_id'] = effective['booking_category']
    if context == 'invoice-review' and effective['confirmed_cost_defaults']:
        values.update(cost_category=effective['invoice_cost_category'], recoverable=effective['invoice_recoverable'])
    if context == 'housing-confirmation':
        values.update(housing_provider_name=effective['document_sender'], housing_provider_address=effective['document_address'],
                      issuer_name=effective['document_signature'], issuer_role=effective['document_profile'])
    sequence = catalogue.rule(unit, 'global', 'sequence:contracts')
    revisions = [catalogue.rule(unit, 'global', key) for key in sorted(catalogue.GLOBAL_ONLY)] if context == 'contracts' else []
    return {'values': values, 'numbering_enabled': context == 'contracts' and bool(effective['contract_number_prefix']),
            'revision': state.digest('draft-preview', [unit.actor_id, context, property_id, effective, sequence, revisions]),
            'policy': 'Nur neue leere Entwurfsfelder; keine nachträgliche Änderung gespeicherter Datensätze.'}, effective, sequence


def preview(store, actor_id, context, property_id=None):
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        return _preview(unit, context, property_id)[0]


def _allocate(unit, effective, sequence):
    prefix = effective['contract_number_prefix']
    candidate = max(effective['contract_number_start'], sequence['payload'].get('next', 1))
    while True:  # No arbitrary cap: old, already-used numbers are skipped, never recycled.
        if candidate > 999999999:
            raise HTTPException(409, 'Nummernkreis ist erschöpft. Bitte einen neuen Präfix festlegen.')
        number = prefix + str(candidate).zfill(effective['contract_number_width'])
        if unit.db is None:
            with scope_context(None):
                exists = any(row.contract_number == number for row in unit.store.list_contracts())
            reserved = ('contracts', number) in state.memory(unit, 'numbers')
        else:
            # Installation-wide collision oracle only: never returns a hidden row
            # or its identity. The reservation is an internal unique namespace.
            with scope_context(None):
                exists = unit.db.scalar(select(ContractORM.id).where(ContractORM.contract_number == number).limit(1)) is not None
            reserved = unit.db.get(NumberReservationORM, ('contracts', number)) is not None
        if not exists and not reserved:
            break
        candidate += 1
    saved = {'revision': sequence['revision'] + 1, 'payload': {'next': candidate + 1}}
    if unit.db is None:
        unit.insert(state.memory(unit, 'numbers'), ('contracts', number), {'owner_id': unit.actor_id, 'created_at': state.now()})
        unit.insert(state.memory(unit, 'rules'), ('global', 'sequence:contracts'), saved)
    else:
        unit.db.add(NumberReservationORM(domain='contracts', number=number, owner_id=unit.actor_id, created_at=state.now()))
        row = unit.db.get(SettingRuleORM, ('global', 'sequence:contracts'))
        if row is None:
            row = SettingRuleORM(scope='global', key='sequence:contracts')
            unit.db.add(row)
        row.revision, row.payload, row.updated_at = saved['revision'], saved['payload'], state.now()
        unit.db.flush()
    return number


def apply(store, actor_id, body):
    try:
        with archive.work(store, actor_id, write_areas=(CONTEXTS.get(body['context'], '/invalid-defaults'),)) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            current, effective, sequence = _preview(unit, body['context'], body.get('property_id'))
            fingerprint = state.digest('new-draft', body)
            prior = state.replay(unit, body['idempotency_key'], fingerprint)
            if prior is not None:
                return prior
            if current['revision'] != body['expected_revision']:
                raise HTTPException(409, 'Vorgaben oder Nummernkreis wurden geändert. Vorschau erneut laden.')
            values = current['values']
            if current['numbering_enabled']:
                values['contract_number'] = _allocate(unit, effective, sequence)
            result = {'values': values, 'basis_revision': current['revision']}
            catalogue.record_audit(unit, body['idempotency_key'], 'draft_defaults', body['context'], {}, result)
            state.remember(unit, body['idempotency_key'], fingerprint, result)
            return result
    except IntegrityError:
        raise HTTPException(409, 'Nummer wurde gleichzeitig reserviert. Bitte Vorschau neu laden.') from None
    except SQLAlchemyError:
        raise HTTPException(503, 'Entwurfsvorgabe nicht bestätigt. Denselben Befehl erneut versuchen.') from None
