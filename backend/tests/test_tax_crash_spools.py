"""An actual killed process cannot leave tax plaintext indefinitely on restart."""
import os
import subprocess
import sys
from pathlib import Path

from backend.services.tax_temp import reap_abandoned, tax_workspace


def test_hard_exit_spool_is_reaped_but_live_and_unknown_paths_survive(tmp_path):
    code = """
import os, sys
from backend.services.tax_temp import tax_workspace
with tax_workspace(sys.argv[1]) as path:
    (path / 'source.jsonl').write_bytes(b'synthetic original source')
    os._exit(17)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], env=environment,
        capture_output=True, check=False, timeout=45)
    assert result.returncode == 17, result.stderr.decode(errors="replace")
    abandoned = list(tmp_path.glob("tax-*"))
    assert len(abandoned) == 1 and (abandoned[0] / "source.jsonl").read_bytes() == b"synthetic original source"
    unknown = tmp_path / "tax-not-owned"
    unknown.mkdir()
    (unknown / "source.jsonl").write_bytes(b"never touch unknown bytes")
    with tax_workspace(tmp_path) as active:
        (active / "source.jsonl").write_bytes(b"active bytes")
        assert not abandoned[0].exists()
        with tax_workspace(tmp_path):
            assert (active / "source.jsonl").read_bytes() == b"active bytes"
            assert (unknown / "source.jsonl").read_bytes() == b"never touch unknown bytes"
    assert not active.exists()
    assert (unknown / "source.jsonl").read_bytes() == b"never touch unknown bytes"


def test_changed_owner_marker_never_authorizes_recursive_cleanup(tmp_path):
    with tax_workspace(tmp_path) as active:
        (active / ".tax-owner.json").write_text('{}', encoding="utf-8")
        (active / "original").write_bytes(b"protected")
        reap_abandoned(tmp_path)
        assert (active / "original").read_bytes() == b"protected"
