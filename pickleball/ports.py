"""Small adapter contracts used by application use cases."""
from typing import Protocol

class Repository(Protocol):
    def get(self, session_id): ...
    def save(self, session, expected_revision=None): ...

class Clock(Protocol):
    def now(self): ...

class Realtime(Protocol):
    def publish(self, session_id, revision): ...

class RepositoryConflict(Exception):
    """Another writer committed since the caller read its snapshot."""

class StorageUnavailable(Exception):
    """Provider unavailable or response invalid; never contains credentials."""
