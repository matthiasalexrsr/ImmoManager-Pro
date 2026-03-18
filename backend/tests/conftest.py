import os
import sys
from pathlib import Path

# Force InMemoryStore for tests — must be set before backend imports.
os.environ.setdefault("SQLITE_PERSISTENT_STORE", "false")
os.environ.setdefault("ALLOW_INMEMORY_FALLBACK", "true")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
