"""Create a private-server environment once, without exposing generated keys."""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.private_server_backup import BackupError, protected_new_file  # noqa: E402


def validated_origin(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or any(char.isspace() for char in value)):
        raise ValueError("Use the private HTTPS origin without credentials, path, query or fragment.")
    host = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host)
        if address.version != 4:
            raise ValueError("Use a DNS hostname or IPv4 address for the private HTTPS endpoint.")
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ValueError("Invalid private server hostname.") from None
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid HTTPS port.")
    rendered_host = f"[{host}]" if ":" in host else host
    return f"https://{rendered_host}" + (f":{port}" if port is not None else ""), host


def configure(path: Path, origin: str, port: int = 8080) -> Path:
    origin, host = validated_origin(origin)
    if not 1024 <= port <= 65535:
        raise ValueError("The local application port must be between 1024 and 65535.")
    # Hex values are safe in Compose interpolation and PostgreSQL connection URLs.
    content = (f"APP_ORIGIN={origin}\nAPP_HOST={host}\nAPP_HTTP_PORT={port}\n"
               "POSTGRES_USER=immo\nPOSTGRES_DB=immomanager\n"
               f"POSTGRES_PASSWORD={secrets.token_hex(32)}\nJWT_SECRET_KEY={secrets.token_hex(48)}\n")
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        raise FileExistsError("The installation environment already exists.")
    with protected_new_file(path) as target:
        target.write(content.encode("utf-8"))
        target.flush()
        os.fsync(target.fileno())
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="Private HTTPS address used by every browser")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / ".env.server")
    args = parser.parse_args()
    try:
        path = configure(args.output, args.origin, args.port)
    except (OSError, ValueError, BackupError) as exc:
        parser.exit(1, f"Configuration was not created: {exc}\n")
    print(f"Created {path}. Preserve this file with your server backups; keys were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
