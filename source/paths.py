"""Stable user data, independent of the executable's installation directory."""
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing


def user_data_dir():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return Path(os.environ.get("TITLEVISION_DATA_DIR", str(root / "TitleVisionAssistant/data")))


def migrate_adjacent_history(app_dir, data_dir):
    """Copy legacy history once; never overwrite an existing destination."""
    source, target = Path(app_dir) / "data/history.sqlite3", Path(data_dir) / "history.sqlite3"
    if target.exists() or not source.exists() or source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix=".sqlite3", dir=target.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as old:
            with closing(sqlite3.connect(temporary)) as new:
                old.backup(new)
                if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Legacy history integrity check failed")
        # On Windows rename refuses an existing target, including a concurrent migration.
        try:
            os.rename(temporary, target)
        except FileExistsError:
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)
