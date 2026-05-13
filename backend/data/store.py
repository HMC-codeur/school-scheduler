from backend.data.memory_store import MemoryStore

_store = MemoryStore()


def get_store() -> MemoryStore:
    return _store
