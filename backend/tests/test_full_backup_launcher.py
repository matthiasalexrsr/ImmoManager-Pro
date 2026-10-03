"""Actual startup exclusion before configuration imports and writes."""

import subprocess
import sys
from pathlib import Path

from backend.backup_operations.state import FileLease, private_directory

def test_actual_launcher_is_fenced_before_any_configuration_writer(tmp_path):
    data = tmp_path / "installation"
    data.mkdir()
    fence = private_directory(data / ".backup-runtime")
    sentinel = data / "configuration-writer-ran"
    script = """
import sys
from pathlib import Path
from backend import __main__ as launcher
def writer(_):
    Path(sys.argv[2]).write_text('unexpected')
launcher._configure_runtime_environment = writer
directory = sys.argv[1]
sys.argv = ['immomanager', '--no-browser', '--data-dir', directory]
try:
    launcher.main()
except RuntimeError as error:
    assert str(error) == 'installation_busy', type(error).__name__
else:
    raise AssertionError('offline owner must reject startup')
assert 'backend.config' not in sys.modules and 'backend.app' not in sys.modules
"""
    with FileLease(fence / "installation.lock"):
        result = subprocess.run([sys.executable, "-c", script, str(data), str(sentinel)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert not sentinel.exists() and not (data / ".env").exists()
