"""Effective settings catalogue over the existing preference/config authorities."""
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .. import config as runtime_config
from ..config import settings
from ..db.daily_models import SettingRuleORM
from ..db.orm_models import UserPreferencesORM
from . import daily_state as state
from . import document_versions as archive
from . import workspace_contexts as contexts
from .portfolio_scope import scope_context, scope_from_user

DEFAULTS = dict(theme="light", locale="de-DE", sidebar_collapsed=False, items_per_page=25,
                date_format="DD.MM.YYYY", currency="EUR", default_due_day=1,
                email_notifications="important", reminder_days="7")
ORM_KEYS = frozenset(DEFAULTS)
DEFAULTS.update(density="comfortable", start_page="/", quiet_start="", quiet_end="")
DEFAULTS.update(currency_display='symbol', document_sender='', document_address='', document_signature='',
                document_profile='housing_provider', booking_category='', invoice_cost_category='',
                invoice_recoverable=False, confirmed_cost_defaults=False,
                contract_number_prefix='', contract_number_start=1, contract_number_width=5)
DEFAULTS.update(bank_import_format='csv', bank_csv_encoding='utf-8-sig', bank_csv_delimiter=';', bank_csv_decimal='.',
                bank_csv_date_format='%Y-%m-%d', bank_csv_date_column='date', bank_csv_amount_column='amount', bank_csv_text_column='text',
                preferred_connection='')
LABELS = dict(theme="Farbschema", locale="Sprache und Zahlenformat", sidebar_collapsed="Seitenleiste einklappen",
              items_per_page="Zeilen je Tabelle", date_format="Datumsformat", currency="Bisherige Währungspräferenz (Quellwährung bleibt maßgeblich)",
              default_due_day="Fälligkeitstag für neue Forderungsentwürfe", email_notifications="E-Mail-Hinweise",
              reminder_days="Erinnerungsvorlauf in Tagen")
LABELS.update(density="Tabellendichte", start_page="Persönliche Startseite", quiet_start="Ruhezeit ab (Europe/Berlin)", quiet_end="Ruhezeit bis (Europe/Berlin)")
LABELS.update(currency_display='Währungsdarstellung (Quellwährung)', document_sender='Briefkopf: Name des Wohnungsgebers',
              document_address='Briefkopf: Anschrift des Wohnungsgebers', document_signature='Unterschriftszeile: Ausstellername (keine elektronische Signatur)',
              document_profile='Dokumentprofil: Ausstellerrolle der Wohnungsgeberbestätigung', booking_category='Kostenregel: Kategorie für neue manuelle Buchungsentwürfe',
              invoice_cost_category='Kostenregel: Kostenart für neue manuelle Rechnungseingänge', invoice_recoverable='Kostenregel: Umlagefähig für neue Rechnungseingänge',
              confirmed_cost_defaults='Kostenregeln ausdrücklich als Entwurfsvorgabe bestätigt', contract_number_prefix='Mietvertragsnummer: Präfix (leer deaktiviert)',
              contract_number_start='Mietvertragsnummer: Startwert', contract_number_width='Mietvertragsnummer: Mindeststellen')
LABELS.update(bank_import_format='Bankimportprofil: Dateiformat', bank_csv_encoding='Bankimportprofil: CSV-Zeichensatz',
              bank_csv_delimiter='Bankimportprofil: CSV-Trennzeichen', bank_csv_decimal='Bankimportprofil: CSV-Dezimalzeichen',
              bank_csv_date_format='Bankimportprofil: CSV-Datumsformat', bank_csv_date_column='Bankimportprofil: Datumsspalte',
              bank_csv_amount_column='Bankimportprofil: Betragsspalte', bank_csv_text_column='Bankimportprofil: Verwendungszweckspalte',
              preferred_connection='Bevorzugte bestehende Integrationsverbindung')
CHOICES: dict[str, list[Any]] = dict(theme=["light", "dark", "system"], locale=["de-DE", "en-US", "es-ES"],
               date_format=["DD.MM.YYYY", "YYYY-MM-DD", "MM/DD/YYYY"], currency=["EUR", "CHF", "USD"],
               email_notifications=["all", "important", "none"], items_per_page=[10,25,50,100],
               sidebar_collapsed=[False, True], density=["comfortable", "compact"], start_page=["/", "/work-center", "/properties", "/tasks", "/notifications"])
BUSINESS = {"default_due_day", "reminder_days"}
GLOBAL_ONLY = {'contract_number_prefix', 'contract_number_start', 'contract_number_width'}
BUSINESS |= GLOBAL_ONLY | {'document_sender', 'document_address', 'document_signature', 'document_profile',
                           'booking_category', 'invoice_cost_category', 'invoice_recoverable', 'confirmed_cost_defaults'}
CHOICES.update(currency_display=['symbol', 'code'], document_profile=['housing_provider', 'authorized_person'],
               invoice_recoverable=[False, True], confirmed_cost_defaults=[False, True])
CHOICES.update(bank_import_format=['csv', 'mt940', 'camt'], bank_csv_encoding=['utf-8-sig', 'cp1252', 'latin-1', 'utf-16'],
               bank_csv_delimiter=[';', ',', '\t', '|'], bank_csv_decimal=['.', ','], bank_csv_date_format=['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'])
TEXT_KEYS = {'document_sender', 'document_address', 'document_signature', 'booking_category', 'invoice_cost_category', 'contract_number_prefix'}
TEXT_KEYS |= {'bank_csv_date_column', 'bank_csv_amount_column', 'bank_csv_text_column', 'preferred_connection'}
ENV_KEYS = {"backup_daily_at": "Uhrzeit der täglichen Sicherung", "backup_keep_daily": "Tägliche Sicherungen aufbewahren",
            "backup_keep_monthly": "Monatliche Sicherungen aufbewahren", "backup_schedule_enabled": "Automatische Sicherung",
            "job_scheduler_enabled": "Hintergrundverarbeitung", "restore_probe_day": "Tag der Wiederherstellungsprobe"}


def record_audit(unit, command_key, action, identifier, before, after):
    from .. import audit as audit_service
    from ..models import AuditLogEntry
    audit = dict(id=hashlib.sha256((unit.actor_id + ':' + action + ':' + command_key).encode()).hexdigest(),
                 user_id=unit.actor_id, username=unit.user.get('username'), action=action,
                 entity_type='setting' if action == 'settings_change' else 'session' if action == 'session_revoke' else 'draft_defaults',
                 entity_id=identifier, changes=json.dumps({'before': before, 'after': after}, ensure_ascii=False, default=str), timestamp=state.now())
    if unit.db is None:
        if not isinstance(audit_service._audit_store, audit_service.InMemoryAuditStore):
            raise HTTPException(503, 'Auditjournal passt nicht zum aktiven Speicher.')
        unit.append(audit_service._audit_store._logs, AuditLogEntry(**audit), lock=audit_service._audit_store._lock)
    else:
        from ..db.orm_models import AuditLogORM
        unit.db.add(AuditLogORM(**audit))
        unit.db.flush()


def validate(values):
    if set(values) - DEFAULTS.keys():
        raise HTTPException(422, "Unbekannte Einstellung.")
    for key, value in values.items():
        if key in TEXT_KEYS and (not isinstance(value, str) or len(value) > (1500 if key == 'document_address' else 120)
                                or any(ord(char) < 32 and not (key == 'document_address' and char == '\n') for char in value)):
            raise HTTPException(422, 'Ungültiger Text für ' + LABELS[key] + '.')
        if key == 'contract_number_prefix' and (not isinstance(value, str) or value and not re.fullmatch(r'[A-Za-z0-9ÄÖÜäöüß._/-]{1,40}', value)):
            raise HTTPException(422, 'Nummernpräfix enthält unzulässige Zeichen.')
        if key in ('contract_number_start', 'contract_number_width') and (type(value) is not int or not 1 <= value <= (999999999 if key.endswith('start') else 12)):
            raise HTTPException(422, 'Ungültige Nummernkreisgrenze.')
        if key in CHOICES and (type(value) is not type(DEFAULTS[key]) or value not in CHOICES[key]):
            raise HTTPException(422, f"Ungültiger Wert für {LABELS[key]}.")
        if key == "default_due_day" and (type(value) is not int or not 1 <= value <= 31):
            raise HTTPException(422, "Fälligkeitstag muss zwischen 1 und 31 (29–31: letzter verfügbarer Monatstag) liegen.")
        if key == "reminder_days" and (not isinstance(value, str) or not value.isdecimal() or not 0 <= int(value) <= 365):
            raise HTTPException(422, "Erinnerungsvorlauf muss zwischen 0 und 365 Tagen liegen.")

        if key in ("quiet_start", "quiet_end") and (not isinstance(value, str) or value != "" and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value)):
            raise HTTPException(422, "Ruhezeiten im Format HH:MM angeben oder beide Felder leeren.")


def personal(unit):
    if unit.db is None:
        return deepcopy(state.memory(unit, "preferences").get(unit.actor_id, {}))
    row = unit.db.scalar(select(UserPreferencesORM).where(UserPreferencesORM.user_id == unit.actor_id))
    metadata = state.get(unit, "preferences")["payload"]
    keys = metadata.get("explicit_keys", list(ORM_KEYS))
    extra = metadata.get("extra_values", {})
    return {key: getattr(row, key) if key in ORM_KEYS else extra[key] for key in keys if key in ORM_KEYS or key in extra} if row else {}


def setting_allowed(unit, key):
    from ..permissions import may_write
    area = ('/integrations' if key == 'preferred_connection' else '/bookings' if key.startswith('bank_') or key == 'booking_category'
            else '/invoice-review/receipts' if key.startswith('invoice_') or key == 'confirmed_cost_defaults'
            else '/documents' if key.startswith('document_') else None)
    return (area is None or may_write(unit.user['role'], area)) and (key != 'preferred_connection' or scope_from_user(unit.user).unrestricted)


def prefs(store, actor_id):
    with archive.work(store, actor_id) as unit:
        return {**{key: effective(unit, key)[0] for key in DEFAULTS}, "_revision": state.get(unit, "preferences")["revision"]}


def effective_values(store, actor_id, property_id=None):
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        if property_id:
            contexts.resolve_context(unit.store, "property", property_id, actor_id)
        return {key: effective(unit, key, property_id)[0] for key in DEFAULTS}


def rule(unit, scope, key):
    if unit.db is None:
        return deepcopy(state.memory(unit, "rules").get((scope, key), {"revision": 0, "payload": {}}))
    row = unit.db.scalar(select(SettingRuleORM).where(SettingRuleORM.scope == scope, SettingRuleORM.key == key).with_for_update())
    return {"revision": row.revision, "payload": deepcopy(row.payload)} if row else {"revision": 0, "payload": {}}


def effective(unit, key, property_id=None):
    value, origin = DEFAULTS[key], "Standard"
    if key in BUSINESS:
        for scope in ("global", "object:" + property_id if property_id else None):
            if scope:
                data = rule(unit, scope, key)["payload"]
                if "value" in data:
                    value, origin = data["value"], scope
    own = personal(unit)
    if key in own:
        value, origin = own[key], "Persönlich"
    return value, origin


def catalogue(store, actor_id, property_id=None):
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        if property_id:
            contexts.resolve_context(unit.store, "property", property_id, actor_id)
        own = personal(unit)
        result = []
        admin = unit.user["role"] in ("eigentuemer", "verwalter")
        for key in DEFAULTS:
            if not setting_allowed(unit, key):
                continue
            value, origin = effective(unit, key, property_id)
            choices = CHOICES.get(key)
            if key == 'booking_category':
                choices = [{'value': '', 'label': 'Keine Vorgabe'}] + [{'value': row.id, 'label': row.name} for row in unit.store.list_categories()]
            if key == 'preferred_connection':
                from ..db.integration_connection_models import IntegrationConnectionORM
                from .integrations import connection_storage
                rows = (unit.db.scalars(select(IntegrationConnectionORM).where(IntegrationConnectionORM.archived.is_(False))).all()
                        if unit.db is not None else [row for row in connection_storage.memory(unit, IntegrationConnectionORM).values() if not row.archived])
                choices = [{'value': '', 'label': 'Keine bevorzugte Verbindung'}] + [{'value': row.id, 'label': row.name} for row in rows]
            if key not in GLOBAL_ONLY:
                result.append(dict(key=key, label=LABELS[key], value=value, origin=origin, scope="personal", editable=key != "currency",
                               revision=state.get(unit, "preferences")["revision"], choices=choices, input_type="time" if key in ("quiet_start", "quiet_end") else 'text' if key in TEXT_KEYS else "number",
                               inherited=key not in own, restart_required=False, secret=False,
                               group="Benachrichtigungen" if key in ("email_notifications", "reminder_days", "quiet_start", "quiet_end") else 'Dokumente und Kostenregeln' if key in BUSINESS else "Ansicht und Arbeitsweise"))
            if admin and key in BUSINESS:
                for scope in ("global" if scope_from_user(unit.user).unrestricted else None, "object:" + property_id if property_id and key not in GLOBAL_ONLY else None):
                    if scope:
                        saved = rule(unit, scope, key)
                        result.append(dict(key=key, label=LABELS[key], value=saved["payload"].get("value", DEFAULTS[key]),
                                           origin=scope if saved["payload"] else "Standard", scope=scope, editable=True,
                                           revision=saved["revision"], choices=choices, input_type='text' if key in TEXT_KEYS else 'number', restart_required=False, secret=False, group="Fachliche Vorgaben"))
        if admin and scope_from_user(unit.user).unrestricted:
            for key, label in ENV_KEYS.items():
                result.append(dict(key=key, label=label, value=getattr(settings, key), scope="installation", origin=getattr(runtime_config, "SETTING_ORIGINS", {}).get(key, "Unbekannt (beim Start nicht erfasst)"),
                                   editable=False, restart_required=True, secret=False, group="Sicherung und Betrieb"))
            # Never read or serialize credential values into this catalogue.
            result.append(dict(key="integration_secrets", label="Zugangsdaten und Schlüssel", value="••••••", origin="Geschützte bestehende Geheimnisablage",
                               scope="installation", editable=False, secret=True, restart_required=False, group="Integrationen"))
        return {"items": result}


def _update(store, actor_id, values, base_revision=None, idempotency_key=None, scope="personal", reset=False):
    validate(values)
    if not values:
        raise HTTPException(422, 'Mindestens eine Einstellung angeben.')
    if set(values) & GLOBAL_ONLY and scope != 'global':
        raise HTTPException(422, 'Nummernkreise gelten installationsweit.')
    if scope != "personal" and (set(values) - BUSINESS or not (scope == "global" or scope.startswith("object:"))):
        raise HTTPException(422, "Diese Einstellung ist nur persönlich zulässig.")
    area = "/auth/users/me/preferences" if scope == "personal" else "/properties"
    with archive.work(store, actor_id, write_areas=(area,)) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        if any(not setting_allowed(unit, key) for key in values):
            raise HTTPException(403, 'Diese Fachvorgabe ist mit den aktuellen Rechten nicht bearbeitbar.')
        if values.get('booking_category'):
            contexts.resolve_context(unit.store, 'category', values['booking_category'], actor_id)
        if values.get('preferred_connection'):
            from .setting_consumers import connection_selection
            connection_selection(unit, values['preferred_connection'])
        if scope != "personal":
            if unit.user["role"] not in ("eigentuemer", "verwalter"):
                raise HTTPException(403, "Fachliche Vorgaben benötigen Verwaltungsrechte.")
            if scope == "global" and not scope_from_user(unit.user).unrestricted:
                raise HTTPException(403, "Installationsweite Vorgaben benötigen Zugriff auf alle Bestände.")
            if scope.startswith("object:"):
                contexts.resolve_context(unit.store, "property", scope[7:], actor_id, lock=True)
            if len(values) != 1:
                raise HTTPException(422, "Fachliche Vorgaben einzeln ändern.")
        before = personal(unit) if scope == "personal" else rule(unit, scope, next(iter(values)))
        body = dict(values=values, base_revision=base_revision, scope=scope, reset=reset)
        fingerprint = state.digest("settings", body)
        saved = state.replay(unit, idempotency_key, fingerprint) if idempotency_key else None
        if saved is not None:
            return saved
        if scope == "personal":
            revision = state.get(unit, "preferences")["revision"]
            if base_revision is None:
                base_revision = revision  # compatibility route, serialized partial update
            after = {**before, **values}
            if reset:
                after = {k: v for k, v in before.items() if k not in values}
            state.put(unit, "preferences", {"explicit_keys": sorted(after), "extra_values": {k: v for k, v in after.items() if k not in ORM_KEYS}}, base_revision)
            if unit.db is None:
                unit.insert(state.memory(unit, "preferences"), actor_id, after)
            else:
                row = unit.db.scalar(select(UserPreferencesORM).where(UserPreferencesORM.user_id == actor_id))
                if row is None:
                    row = UserPreferencesORM(user_id=actor_id)
                    unit.db.add(row)
                # Presence metadata distinguishes inherited values from defaults in old required columns.
                for key, value in {**DEFAULTS, **after}.items():
                    if key in ORM_KEYS:
                        setattr(row, key, value)
                unit.db.flush()
            result = {**{key: effective(unit, key)[0] for key in DEFAULTS}, "_revision": revision + 1}
        else:
            key = next(iter(values))
            if before["revision"] != base_revision:
                raise HTTPException(409, "Vorgabe wurde zwischenzeitlich geändert. Bitte vergleichen.")
            payload = {} if reset else {"value": values[key]}
            result = dict(revision=base_revision + 1, payload=payload)
            if unit.db is None:
                unit.insert(state.memory(unit, "rules"), (scope, key), result)
            else:
                rule_row = unit.db.scalar(select(SettingRuleORM).where(SettingRuleORM.scope == scope, SettingRuleORM.key == key).with_for_update())
                if rule_row is None:
                    rule_row = SettingRuleORM(scope=scope, key=key)
                    unit.db.add(rule_row)
                rule_row.revision, rule_row.payload, rule_row.updated_at = result["revision"], payload, state.now()
                unit.db.flush()
        # Reuse the existing permanent business audit, in the SAME transaction.
        # Command receipts may disappear with an account; global rule history must not.
        if idempotency_key:
            audit_id = hashlib.sha256((actor_id + ":settings:" + idempotency_key).encode()).hexdigest()
            audit = dict(id=audit_id, user_id=actor_id, username=unit.user.get("username"), action="settings_change",
                         entity_type="setting", entity_id=scope if scope != "personal" else "personal:" + actor_id,
                         changes=json.dumps({"before": before, "change": body, "after": result}, ensure_ascii=False), timestamp=state.now())
            if unit.db is None:
                from .. import audit as audit_service
                from ..models import AuditLogEntry
                if not isinstance(audit_service._audit_store, audit_service.InMemoryAuditStore):
                    raise HTTPException(503, "Auditjournal passt nicht zum aktiven Speicher.")
                unit.append(audit_service._audit_store._logs, AuditLogEntry(**audit), lock=audit_service._audit_store._lock)
            else:
                from ..db.orm_models import AuditLogORM
                unit.db.add(AuditLogORM(**audit))
                unit.db.flush()
        # The immutable command result is also the settings audit (actor, time, before/after).
        if idempotency_key:
            state.remember(unit, idempotency_key, fingerprint, {"response": result, "before": before, "change": body})
        return {"response": result, "before": before, "change": body} if idempotency_key else result


def email_policy(values, severity, moment=None):
    preference = values["email_notifications"]
    allowed = preference == "all" or preference == "important" and severity in ("warning", "error", "critical")
    start, end = values.get("quiet_start", ""), values.get("quiet_end", "")
    if allowed and start and end and start != end:
        current = moment or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        clock = current.astimezone(ZoneInfo("Europe/Berlin")).strftime("%H:%M")
        quiet = start <= clock < end if start < end else clock >= start or clock < end
        allowed = not quiet
    return allowed


def email_allowed(store, actor_id, severity, moment=None):
    """Outbox eligibility only; no sending. Quiet hours use the installation zone."""
    return email_policy(prefs(store, actor_id), severity, moment)


def email_selection(store, actor_id, *, cursor=None, limit=100, moment=None):
    """Bounded recipient-specific policy hook; never queues or sends a message.

    The communication worker must recheck this policy AND the source at claim
    and dispatch time. Returned source revisions bind the proposed selection.
    Business correspondence/dunning is deliberately outside this hook.
    """
    from .notification_inbox import inbox
    page = inbox(store, actor_id, status='unread', limit=limit, cursor=cursor)
    values = prefs(store, actor_id)
    selected = [dict(notification_id=row['id'], source=row['target']) for row in page['items']
                if row['target'] and email_policy(values, row['severity'], moment)]
    return {'items': selected, 'snapshot': page['snapshot'], 'next_cursor': page['next_cursor'],
            'unread_count': page['unread_count'], 'scheduled': False}


def update(store, actor_id, values, base_revision=None, idempotency_key=None, scope="personal", reset=False):
    try:
        return _update(store, actor_id, values, base_revision, idempotency_key, scope, reset)
    except IntegrityError as exc:
        raise HTTPException(409, "Gleichzeitige Einstellungsänderung. Bitte aktuellen Stand vergleichen.") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Speicherung nicht bestätigt. Bitte denselben Befehl erneut versuchen.") from exc
