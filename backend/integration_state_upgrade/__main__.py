"""Explicit connection-state maintenance; passphrases never enter arguments."""

import argparse
import errno
import getpass
import json
from pathlib import Path

from .service import IntegrationUpgradeError, operations, rollback, status, upgrade

MESSAGES = {
    "installation_busy": "Die Installation läuft oder wird gewartet. Anwendung und Hintergrundprozesse zuerst vollständig beenden.",
    "integration_upgrade_offline_required": "Anwendung und Hintergrundprozesse beenden und --offline angeben.",
    "integration_upgrade_database_busy": "Die ausgewählte Datenbank wird beschrieben oder ist nicht verfügbar. Pfad prüfen und Schreiber beenden; Integrationszustand bleibt unverändert.",
    "integration_state_missing": "Die ausgewählte Integrationsdatei fehlt. Den richtigen vorhandenen Bestand ausdrücklich wählen.",
    "integration_state_already_encrypted": "Der Integrationszustand ist bereits verschlüsselt. Bei einer unterbrochenen Operation deren Status prüfen.",
    "integration_upgrade_timed_out": "Das gewählte Zeitbudget wurde überschritten. Operationsstatus prüfen; ein größeres positives Kapazitätsprofil verwenden.",
    "state_revision_conflict": "Der Integrationszustand wurde seit der Prüfung geändert. Keine Wiederholung ohne erneute Bestandsprüfung; vorhandene Operation und Sicherung erhalten.",
    "integration_upgrade_selection_changed": "Auswahl oder Konfiguration stimmt nicht mehr mit der Operation überein. Den unveränderten richtigen Bestand wählen.",
    "integration_upgrade_archive_changed": "Die gebundene Sicherung wurde ersetzt oder verändert. Das unveränderte vollständige Archiv dieser Operation verwenden.",
    "integration_upgrade_return_refused_after_changes": "Integrationszugänge wurden nach der Umstellung geändert. Rückweg verweigert, damit spätere Änderungen erhalten bleiben.",
    "legacy_return_payload_changed": "Der aktuelle verschlüsselte Inhalt unterscheidet sich vom gesicherten Original. Rückweg verweigert; spätere Änderungen bleiben erhalten.",
    "integration_upgrade_backup_not_verified": "Für diese Operation wurde noch keine vollständige Wiederherstellungsprobe bestätigt. Originalzustand und vorhandene Sicherung prüfen.",
    "integration_upgrade_receipt_invalid": "Der geschützte Operationsnachweis ist ungültig oder nicht zugänglich. Richtige Installation und Operationskennung prüfen.",
    "integration_upgrade_selection_invalid": "Datenbank-, Upload- oder Konfigurationsauswahl ist ungültig. Die vollständige vorhandene Installation und deren ausdrücklich gespeicherte Konfiguration wählen.",
    "integration_upgrade_capacity_invalid": "Kapazitätsprofil oder Zeitbudget ist ungültig. Dokumentierte positive Größen und endliche Zeitwerte wählen.",
    "integration_upgrade_configuration_budget_exceeded": "Die Konfigurationsdatei überschreitet das gewählte Ressourcenbudget. Die richtige Datei prüfen oder das dokumentierte Größenbudget im Kapazitätsprofil erhöhen.",
    "integration_upgrade_archive_not_verified": "Passphrase oder vollständiges Archiv konnte nicht bestätigt werden. Richtige Passphrase und unveränderte Sicherung prüfen; der Integrationszustand wurde nicht zurückgesetzt.",
    "integration_upgrade_passphrases_differ": "Die eingegebenen Passphrasen stimmen nicht überein. Vorgang mit derselben Passphrase in beiden Eingaben erneut starten.",
    "integration_upgrade_page_invalid": "Positive Seitengröße und gültige Operationskennung der vorherigen Seite verwenden.",
    "integration_upgrade_disk_full": "Speicherplatz fehlt. Platz schaffen, vorhandene Sicherung erhalten und den Operationsstatus vor einer Wiederholung prüfen.",
    "state_busy": "Ein anderer Integrationsschreiber hält die Datei. Schreiber beenden; mit passendem --state-lock-timeout erneut prüfen.",
    "state_io_failed": "Datei oder geschützter Operationsnachweis konnte nicht sicher verarbeitet werden. Dateirechte und Speicherplatz prüfen; Operationsstatus vor einer Wiederholung prüfen.",
    "invalid_lock_timeout": "Eine endliche positive Wartezeit mit --state-lock-timeout wählen.",
    "durability_unconfirmed": "Das Dateiergebnis ist noch nicht bestätigt. Operationsstatus prüfen; weder Umstellung noch Rückweg blind wiederholen.",
    "encryption_key_unavailable": "Die stabilen Verschlüsselungsschlüssel fehlen oder sind ungültig. Vollständige Schlüsselkonfiguration der ausgewählten Installation wiederherstellen.",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("convert", "list", "status", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument("--database", type=Path)
        command.add_argument("--uploads", type=Path)
        command.add_argument("--integrations", type=Path)
        command.add_argument("--capacity-file", type=Path)
        command.add_argument("--timeout-seconds", type=float)
        command.add_argument("--state-lock-timeout", type=float, default=5.0,
                             help="Positives Zeitbudget für den Integrations-Dateilock")
        if name in {"convert", "rollback"}:
            command.add_argument("--offline", action="store_true", required=True)
        if name == "convert":
            command.add_argument("--output", type=Path, required=True, help="Neues verschlüsseltes Vollarchiv")
        elif name != "list":
            command.add_argument("--operation-id", required=True, help="UUID aus dem geschützten Operationsnachweis")
        else:
            command.add_argument("--page-size", type=int, default=20)
            command.add_argument("--after", help="Operations-UUID der vorherigen Ergebnisseite")
    args = parser.parse_args(argv)
    try:
        if args.command in {"list", "status"}:
            result = operations(args) if args.command == "list" else status(args)
        else:
            password = getpass.getpass("Passphrase der vollständigen Sicherung: ")
            if args.command == "convert" and password != getpass.getpass("Passphrase wiederholen: "):
                raise IntegrationUpgradeError("integration_upgrade_passphrases_differ")
            result = upgrade(args, password) if args.command == "convert" else rollback(args, password)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        from backend.backup_operations.plan import BackupOperationError
        from backend.legacy_sqlite_upgrade.service import LegacyUpgradeError
        from backend.services.integrations.config_store import ConfigStoreError
        if isinstance(error, (ConfigStoreError, BackupOperationError)):
            code = error.code
        elif isinstance(error, (IntegrationUpgradeError, LegacyUpgradeError)):
            code = str(error)
        elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
            code = "integration_upgrade_disk_full"
        else:
            code = "integration_upgrade_source_or_archive_unproved"
        print(json.dumps({"error": code, "message": MESSAGES.get(code,
            "Wartung abgebrochen. Geschützten Operationsstatus und vollständige unveränderte Sicherung prüfen; keine automatische Wiederholung."),
            "operations_command": "python -m backend.integration_state_upgrade list --data-dir <installation>"},
            ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
