"""Explicit legacy SQLite maintenance. Passphrases never enter arguments."""

import argparse
import getpass
import json
from pathlib import Path

from .schema import LegacySchemaError
from .service import LegacyUpgradeError, installation_lease, rollback, status, upgrade

MESSAGES = {
    "installation_busy": "Die Installation läuft oder wird bereits gewartet. Anwendung zuerst vollständig beenden.",
    "legacy_database_busy": "Ein SQLite-Schreiber arbeitet noch. Zuerst alle Datenbank-Schreiber vollständig beenden; der Bestand bleibt unverändert.",
    "legacy_schema_unrecognised": "Das vollständige Altschema ist nicht eindeutig unterstützt. Der Bestand bleibt unverändert; kompatible Sicherung und Schema prüfen.",
    "legacy_database_already_versioned": "Die Datenbank besitzt bereits eine Schema-Version. Den regulären versionsgebundenen Wartungsweg verwenden.",
    "legacy_offline_required": "Zuerst Anwendung und Hintergrundschreiber beenden und --offline angeben.",
    "legacy_rollback_refused_after_changes": "Seit dem Upgrade wurde der Bestand verändert. Rückweg verweigert, damit keine neueren Daten verloren gehen.",
    "legacy_installation_files_changed": "Originale oder Einstellungen wurden verändert. Unveränderte vollständige Sicherung prüfen.",
    "legacy_target_requires_reference_validation": "Diese Programmversion benötigt zuerst einen geprüften Upgrade-Referenzkatalog.",
    "legacy_operation_timed_out": "Der Vorgang hat sein Zeitbudget überschritten. Status prüfen; bei Bedarf ein größeres positives Budget wählen.",
    "legacy_database_budget_exceeded": "Die Datenbank überschreitet das gewählte Kapazitätsprofil. Ein passendes positives Sicherungsbudget wählen; der Bestand bleibt unverändert.",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "upgrade", "status", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument("--database", type=Path)
        command.add_argument("--uploads", type=Path)
        command.add_argument("--integrations", type=Path)
        command.add_argument("--capacity-file", type=Path)
        command.add_argument("--timeout-seconds", type=float)
        if name in {"upgrade", "rollback"}:
            command.add_argument("--offline", action="store_true", required=True)
        if name == "upgrade":
            command.add_argument("--output", type=Path, required=True, help="Neues verschlüsseltes Vollarchiv")
        if name in {"status", "rollback"}:
            command.add_argument("--operation-id", required=True, help="UUID aus dem Upgrade-Ergebnis")
    args = parser.parse_args(argv)
    try:
        # Capacity and recovery imports belong inside the installation fence.
        if args.command == "inspect":
            with installation_lease(args.data_dir) as root:
                from .schema import inspect_legacy_sqlite
                from .service import _selected
                proof = inspect_legacy_sqlite(_selected(args, root).database)
                result = {"profile_id": proof.profile_id, "source_commit": proof.source_commit,
                          "schema_sha256": proof.schema_sha256, "schema_verified": True,
                          "business_review": "legacy_business_states_require_source_review"}
        else:
            # Service obtains its lease before importing full recovery/settings.
            if args.command == "upgrade":
                password = getpass.getpass("Passphrase der vollständigen Sicherung: ")
                if password != getpass.getpass("Passphrase wiederholen: "):
                    raise LegacyUpgradeError("legacy_passphrases_differ")
                result = upgrade(args, password)
            else:
                result = status(args) if args.command == "status" else rollback(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (LegacyUpgradeError, LegacySchemaError) as error:
        code = str(error)
        print(json.dumps({"error": code, "message": MESSAGES.get(code,
              "Wartung abgebrochen. Status und erhaltene Sicherung prüfen; kein automatischer Bestandsabgleich.")}, ensure_ascii=False))
        return 2
    except Exception as error:
        from backend.backup_operations.plan import BackupOperationError
        code = str(error) if isinstance(error, BackupOperationError) else "legacy_maintenance_aborted"
        print(json.dumps({"error": code, "message": MESSAGES.get(code, "Wartung abgebrochen; vorhandenen Bestand und Sicherung prüfen.")}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
