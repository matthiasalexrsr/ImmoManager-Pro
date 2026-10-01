"""Offline IBAN maintenance. Secrets are read from protected files/getpass, never argv."""

import argparse
import getpass
import json
import os
import stat
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from .services.iban_encryption import IBANEncryptionError, generate_key, keyring_from_configuration
from .services.iban_rotation import (
    VerifiedAccountBackup,
    create_backup_proof,
    inspect_account_encryption,
    rotate_account_ibans,
)


def _protected_read(path: Path) -> bytes:
    from scripts.private_server_backup import _verify_private, private_workspace

    # Exactly selected files; reject links/reparse points and verify owner-only
    # protection using the same platform implementation as private backups.
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or not stat.S_ISREG(info.st_mode):
        raise IBANEncryptionError("ENCRYPTION_CONFIGURATION_FILE_UNSAFE")
    if os.name == "nt":
        with private_workspace() as (workspace, sid):
            _verify_private(path, workspace, sid, protected=False)
    elif info.st_uid != getattr(os, "getuid")() or info.st_mode & 0o077:
        raise IBANEncryptionError("ENCRYPTION_CONFIGURATION_FILE_UNSAFE")
    return path.read_bytes()


def _configuration(path: Path):
    raw = _protected_read(path)
    if path.suffix.lower() == ".json":
        values = json.loads(raw)
    else:
        import io

        values = dotenv_values(stream=io.StringIO(raw.decode("utf-8")), interpolate=False)
    if not isinstance(values, dict):
        raise IBANEncryptionError("ENCRYPTION_CONFIGURATION_INVALID")
    return values


def _engine(values):
    url = values.get("DATABASE_URL") or values.get("database_url")
    if not isinstance(url, str):
        raise IBANEncryptionError("ENCRYPTION_DATABASE_CONFIGURATION_MISSING")
    parsed = make_url(url)
    if parsed.get_backend_name() not in {"sqlite", "postgresql"}:
        raise IBANEncryptionError("ENCRYPTION_DATABASE_UNSUPPORTED")
    if parsed.get_backend_name() == "sqlite" and (
        not parsed.database or parsed.database == ":memory:" or not Path(parsed.database).is_file()
    ):
        raise IBANEncryptionError("ENCRYPTION_DATABASE_CONFIGURATION_MISSING")
    return create_engine(
        parsed,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"timeout": 30} if parsed.get_backend_name() == "sqlite" else {},
    )


def _write(path: Path, values):
    from scripts.private_server_backup import protected_new_file

    with protected_new_file(path) as output:
        output.write((json.dumps(values, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes unrecognized argument values: a
        # pasted secret must not be echoed by an invalid command invocation.
        self.print_usage(sys.stderr)
        self.exit(
            2, "Ungültige Wartungsargumente; Geheimnisse ausschließlich über geschützte Dateien oder stdin eingeben.\n"
        )


def main(argv=None):
    parser = _Parser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    key = sub.add_parser(
        "create-keyring", help="Create a NEW protected key configuration; never overwrite an existing file"
    )
    key.add_argument("--output", type=Path, required=True)
    key.add_argument("--key-id", default="default")
    key.add_argument(
        "--existing-config", type=Path, help="Retain ALL existing keys/index key when adding a rotation key"
    )
    key.add_argument("--legacy-secret-stdin", action="store_true", help="Read the old JWT encryption secret from stdin")
    key.add_argument(
        "--legacy-secret-prompt", action="store_true", help="Read the old JWT encryption secret with getpass"
    )
    proof = sub.add_parser(
        "backup-proof", help="Validate a separately restored full database and create a NEW protected proof file"
    )
    proof.add_argument("--config", type=Path, required=True)
    proof.add_argument("--output", type=Path, required=True)
    for name in ("status", "rotate"):
        command = sub.add_parser(name)
        command.add_argument(
            "--config", type=Path, required=True, help="Protected explicit installation configuration (.env or JSON)"
        )
        command.add_argument(
            "--key-config", type=Path, help="Protected prospective key configuration; DB target stays in --config"
        )
        if name == "rotate":
            command.add_argument(
                "--offline", action="store_true", help="Application and other writers have been stopped"
            )
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--backup-proof", type=Path)
            command.add_argument("--chunk-size", type=int, default=500)
    args = parser.parse_args(argv)
    engine = None
    try:
        if args.command == "create-keyring":
            if args.legacy_secret_stdin and args.legacy_secret_prompt:
                parser.error("Choose one secret input")
            old_values = _configuration(args.existing_config) if args.existing_config else {}
            if old_values:
                old = keyring_from_configuration(old_values)
                keys, index_key, legacy = dict(old.keys), old.index_key or generate_key(), list(old.legacy_jwt_keys)
            else:
                keys, index_key, legacy = {}, generate_key(), []
            if args.key_id in keys:
                raise IBANEncryptionError("ENCRYPTION_KEY_ID_ALREADY_EXISTS")
            if args.legacy_secret_stdin or args.legacy_secret_prompt:
                secret = (
                    sys.stdin.readline().rstrip("\r\n")
                    if args.legacy_secret_stdin
                    else getpass.getpass("Bisheriges JWT-IBAN-Geheimnis: ")
                )
                if not secret:
                    raise IBANEncryptionError("ENCRYPTION_LEGACY_KEY_UNAVAILABLE")
                legacy.append(secret)
            keys[args.key_id] = generate_key()
            values = dict(
                ENCRYPTION_KEY="",
                ENCRYPTION_KEYRING=json.dumps(keys, separators=(",", ":")),
                ENCRYPTION_ACTIVE_KEY_ID=args.key_id,
                ENCRYPTION_INDEX_KEY=index_key,
                ENCRYPTION_LEGACY_JWT_KEYS=json.dumps(legacy),
            )
            keyring_from_configuration(values)  # validate before publishing
            _write(args.output, values)
            result = dict(created=True, key_count=len(keys), retain_old_keys=True)
        else:
            base = _configuration(args.config)
            values = dict(base)
            if getattr(args, "key_config", None):
                extra = _configuration(args.key_config)
                values.update({key: value for key, value in extra.items() if key.upper().startswith("ENCRYPTION_")})
            ring = keyring_from_configuration(values)
            engine = _engine(base)
            if args.command == "backup-proof":
                restored_proof = create_backup_proof(engine, ring)
                _write(args.output, restored_proof.as_dict())
                result = dict(proof_created=True, verified=True, requires_separately_restored_backup=True)
            elif args.command == "status":
                with engine.connect() as connection:
                    from .services.iban_rotation import _read_snapshot

                    _read_snapshot(connection)
                    result = inspect_account_encryption(connection, ring)
            else:
                evidence = (
                    VerifiedAccountBackup.from_dict(json.loads(_protected_read(args.backup_proof)))
                    if args.backup_proof
                    else None
                )
                result = rotate_account_ibans(
                    engine, ring, evidence, offline=args.offline, dry_run=args.dry_run, chunks=args.chunk_size
                )
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        code = exc.code if isinstance(exc, IBANEncryptionError) else "ENCRYPTION_MAINTENANCE_FAILED"
        # Do not include arbitrary file/SQL exception text, chained causes or
        # argparse values in an operator log. Source data remain unchanged.
        print(
            json.dumps(
                dict(
                    error=dict(
                        code=code,
                        message="Wartung abgebrochen. Datenbank, Schlüsselkonfiguration und separat wiederhergestellte vollständige Sicherung prüfen.",
                    )
                )
            )
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
