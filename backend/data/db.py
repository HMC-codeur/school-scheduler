from pathlib import Path
import os


def get_database_path() -> Path:
    configured = os.getenv("SCHOOL_SCHEDULER_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent / "school_scheduler.sqlite3"
