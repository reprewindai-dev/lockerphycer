"""`alembic upgrade head` must persist on a database that already has tables.

alembic/env.py inspects the database first. That inspection opened a transaction which
was left open, so every migration ran inside it, was never committed, and was rolled back
when the connection closed, while the log still said "Running upgrade".
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _alembic(db: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "ENVIRONMENT": "development",
           "SECRET_KEY": os.environ.get("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=REPO, env=env, check=True,
                   capture_output=True, timeout=300)


def _version_and_tables(db: Path):
    con = sqlite3.connect(db)
    try:
        version = con.execute("select version_num from alembic_version").fetchone()[0]
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        return version, tables
    finally:
        con.close()


def test_upgrade_on_an_existing_database_is_committed(tmp_path):
    db = tmp_path / "existing.db"
    _alembic(db, "upgrade", "head")              # fresh install: base schema + chain
    head, _ = _version_and_tables(db)

    # An existing database one migration behind head, without that migration's table.
    con = sqlite3.connect(db)
    con.execute("drop table agreement_acceptances")
    con.commit()
    con.close()
    _alembic(db, "stamp", "a9d4e6c2b7f3")

    _alembic(db, "upgrade", "head")
    version, tables = _version_and_tables(db)
    assert version == head == "b8c2e4f6a1d3"
    assert "agreement_acceptances" in tables
