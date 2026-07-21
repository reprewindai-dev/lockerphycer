from __future__ import annotations

import os
from pathlib import Path

_temp_dir = Path(r"C:\tmp")
_temp_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMP", str(_temp_dir))
os.environ.setdefault("TEMP", str(_temp_dir))
os.environ.setdefault("TMPDIR", str(_temp_dir))
os.environ.setdefault("SECRET_KEY", "dev-only-secret-key-do-not-use-in-production-32+")
