from backend.data.repository import SchedulerRepository
from backend.data.sqlite_repository import SQLiteRepository

_store = SQLiteRepository()


def get_repository() -> SchedulerRepository:
    return _store


def get_store() -> SchedulerRepository:
    return get_repository()
