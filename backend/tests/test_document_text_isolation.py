"""Real subprocesses prove the text reader's wall, memory and output boundaries."""

import os
import sys
import time

import pytest

from backend.services import document_text_process as process
from backend.services.assistant_provider_protocol import ProviderError
from backend.services.document_text_reader import Budget
from backend.services.e_invoice import validator


@pytest.mark.parametrize("failure", ["timeout", "memory", "output", "file"])
def test_reader_resource_failures_are_bounded_and_owned_children_are_stopped(monkeypatch, failure):
    owned = []
    factory = validator.CliProcess
    run = validator._run
    returned: list[tuple[int, str, str]] = []
    errors: list[str] = []

    def capture(*args, **kwargs):
        instance = factory(*args, **kwargs)
        owned.append(instance)
        return instance

    def record_run(*args, **kwargs):
        try:
            result = run(*args, **kwargs)
            returned.append(result)
            return result
        except (validator.ValidatorUnavailable, ProviderError) as error:
            errors.append(error.code if isinstance(error, ProviderError) else str(error))
            raise

    if failure == "timeout":
        code = "import time; time.sleep(60)"
    elif failure == "memory":
        code = "memory=bytearray(2*1024**3)"
    elif failure == "output":
        code = "import sys; sys.stdout.write('x'*2_000_002); sys.stdout.flush()"
    else:
        code = "from pathlib import Path; import sys,time; p=Path(sys.argv[1])/'oversized.bin'; f=p.open('wb'); f.truncate(200*1024**2); f.close(); time.sleep(60)"
    with monkeypatch.context() as patch:
        patch.setattr(validator, "CliProcess", capture)
        patch.setattr(validator, "_run", record_run)
        patch.setattr(process, "TEXT_TIMEOUT_SECONDS", 5)
        patch.setattr(process, "worker_command", lambda folder: [sys.executable, "-c", code, str(folder)])
        started = time.monotonic()
        part = process.read_isolated(b"Own synthetic fixture", "fixture.txt", {}, Budget())
        assert part.complete and part.warning and not part.text
        assert owned and all(instance.process.poll() is not None for instance in owned)
        assert time.monotonic() - started < 12
        if failure == "memory":
            assert returned[0][0] != 0
            assert "MemoryError" in returned[0][2]
        elif failure == "file" and os.name != "nt":
            # RLIMIT_FSIZE rejects truncate before the directory monitor runs.
            assert returned[0][0] != 0 and "File too large" in returned[0][2]
        else:
            expected = {"timeout": "Zeitlimit", "output": "output_too_large", "file": "Arbeitsdateibudget"}[failure]
            assert expected in errors[0]
    # Normal protected extraction still works after each rejected/terminated child.
    valid = process.read_isolated(b"Weiterhin normal lesbar", "normal.txt", {}, Budget())
    assert valid.text == "Weiterhin normal lesbar" and valid.complete and valid.warning is None
