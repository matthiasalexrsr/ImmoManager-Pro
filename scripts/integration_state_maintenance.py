"""Offline maintenance for encrypted integration state.

Explicit files only. No runtime Settings, live auth, provider calls or secret output.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.integrations.config_store import ConfigStoreError  # noqa: E402
from backend.services.integrations.encrypted_config_store import (  # noqa: E402
    FORMAT,
    build_encrypted_integration_store,
)
from backend.services.integrations.integration_state_offline import (  # noqa: E402
    load_explicit_configuration,
    verify_encrypted_integration_state,
)

_DEFAULT_BYTES = 1024 * 1024
_DEFAULT_LOCK_SECONDS = 5.0
_DEFAULT_DEPTH = 64


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected positive integer") from None
    if parsed < 1 or str(parsed) != value.strip():
        raise argparse.ArgumentTypeError("expected positive integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected finite positive number") from None
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("expected finite positive number")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Verify or explicitly migrate private integration state."
    )
    result.add_argument("operation", choices=("verify", "migrate-plaintext"))
    result.add_argument("--state-file", required=True)
    result.add_argument("--configuration", required=True)
    result.add_argument(
        "--max-state-bytes", type=_positive_int, default=_DEFAULT_BYTES
    )
    result.add_argument(
        "--max-configuration-bytes",
        type=_positive_int,
        default=_DEFAULT_BYTES,
    )
    result.add_argument(
        "--lock-timeout",
        type=_positive_float,
        default=_DEFAULT_LOCK_SECONDS,
    )
    result.add_argument(
        "--max-json-depth", type=_positive_int, default=_DEFAULT_DEPTH
    )
    return result


def execute(args: argparse.Namespace) -> dict[str, object]:
    configuration = load_explicit_configuration(
        args.configuration,
        max_bytes=args.max_configuration_bytes,
    )
    if args.operation == "migrate-plaintext":
        store = build_encrypted_integration_store(
            args.state_file,
            configuration,
            max_plaintext_bytes=args.max_state_bytes,
            lock_timeout=args.lock_timeout,
            max_json_depth=args.max_json_depth,
        )
        # The store uses its reviewed lock/temp/fsync/os.replace path. It never
        # creates a plaintext backup or calls providers.
        store.migrate_legacy_plaintext()

    verified = verify_encrypted_integration_state(
        args.state_file,
        configuration,
        max_plaintext_bytes=args.max_state_bytes,
        max_json_depth=args.max_json_depth,
    )
    return {
        "status": "verified_encrypted",
        "format": FORMAT,
        "state_revision": verified["state_revision"],
        "file_size_bytes": verified["file_size_bytes"],
        "plaintext_size_bytes": verified["plaintext_size_bytes"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except ConfigStoreError as error:
        print(
            json.dumps(
                {"status": "failed", "code": error.code},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
