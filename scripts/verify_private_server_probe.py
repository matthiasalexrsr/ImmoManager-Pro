"""Read actual restored tables and compare every extracted file to its archive."""

import argparse
import hashlib
import json
import os
import stat
import sys
import tarfile
import time
from pathlib import Path


def inventory(connection, deadline):
    from sqlalchemy import inspect
    inspector = inspect(connection)
    names = sorted(inspector.get_table_names(schema="public"))
    required = {"users", "auth_setup", "portfolios", "bookings", "receivables", "rent_charges", "payments", "payment_reversals"}
    if not required.issubset(names):
        raise ValueError("incomplete_schema")
    schema, counts = {}, {}
    for name in names:
        if time.monotonic() >= deadline:
            raise TimeoutError()
        columns = [{"name": item["name"], "type": str(item["type"]), "nullable": item["nullable"]}
                   for item in inspector.get_columns(name, schema="public")]
        schema[name] = columns
        quoted = '"public"."' + name.replace('"', '""') + '"'
        counts[name] = connection.exec_driver_sql("SELECT count(*) FROM " + quoted).scalar_one()
    return {"schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "rows": counts}


def verify_files(stream, root, deadline, max_entries, max_bytes):
    count = size = files = 0
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for item in archive:
            count += 1
            size += item.size
            if count > max_entries or size > max_bytes or time.monotonic() >= deadline:
                raise ValueError("probe_budget_exceeded")
            if not (item.isdir() or item.isfile()) or item.name.startswith("/") or ".." in Path(item.name).parts:
                raise ValueError("unsafe_archive")
            path = root / item.name
            for parent in (path, *path.parents):
                if parent == root.parent:
                    break
                if parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & 0x400:
                    raise ValueError("unsafe_restored_file")
            if item.isdir():
                if not path.is_dir():
                    raise ValueError("restored_directory_missing")
                continue
            expected = archive.extractfile(item)
            if expected is None or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size != item.size:
                raise ValueError("restored_file_missing")
            with expected, path.open("rb") as actual:
                while block := expected.read(1024 * 1024):
                    if time.monotonic() >= deadline or actual.read(len(block)) != block:
                        raise ValueError("restored_file_changed")
                if actual.read(1):
                    raise ValueError("restored_file_changed")
            files += 1
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-stdin", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--max-entries", type=int, default=100_000)
    parser.add_argument("--max-bytes", type=int, default=8 * 1024**3)
    args = parser.parse_args(argv)
    try:
        if not 0 < args.timeout_seconds <= 86400 or args.max_entries <= 0 or args.max_bytes <= 0:
            raise ValueError()
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        url = make_url(os.environ["DATABASE_URL"])
        if url.get_backend_name() != "postgresql":
            raise ValueError()
        deadline = time.monotonic() + args.timeout_seconds
        engine = create_engine(url, connect_args={"connect_timeout": max(1, int(args.timeout_seconds))})
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    connection.exec_driver_sql("SET LOCAL statement_timeout = " + str(max(1, int(args.timeout_seconds * 1000))))
                    database = inventory(connection, deadline)
                finally:
                    transaction.rollback()
        finally:
            engine.dispose()
        files = verify_files(sys.stdin.buffer, Path("/data"), deadline, args.max_entries, args.max_bytes) if args.archive_stdin else 0
        print(json.dumps({"verified": True, "database": database, "upload_files": files}, separators=(",", ":")))
        return 0
    except Exception:
        print("private_server_probe_verification_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
