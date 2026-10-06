"""SQLite persistence and transactional import of legacy JSON trip files."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.models import Trip

DATA_DIRECTORY = Path(__file__).resolve().parent.parent / "data"
DEFAULT_DATABASE = DATA_DIRECTORY / "trips.sqlite3"
DEFAULT_IMPORT_FILE = DATA_DIRECTORY / "trips.json"
_trips_adapter = TypeAdapter(list[Trip])

_CREATE_TABLE = """
CREATE TABLE trips (
    id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(id)) > 0),
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer' AND amount > 0),
    payment TEXT NOT NULL CHECK (payment IN ('cash', 'card')),
    commission INTEGER NOT NULL CHECK (
        typeof(commission) = 'integer' AND commission >= 0 AND commission <= amount
    )
)
"""
_INSERT_TRIP = """
INSERT INTO trips (id, start, end, amount, payment, commission)
VALUES (:id, :start, :end, :amount, :payment, :commission)
ON CONFLICT(id) DO NOTHING
"""


class TripStorageError(RuntimeError):
    """The database or import file could not be read, validated, or saved."""


class DuplicateTripError(ValueError):
    """An existing record already owns this trip ID."""

    def __init__(self, existing: Trip) -> None:
        self.existing = existing
        super().__init__(f"Trip ID already exists: {existing.id}")


class SqliteTripStore:
    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self._path = Path(path).expanduser().resolve()
        self._timeout = timeout

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def from_environment(cls) -> "SqliteTripStore":
        configured_path = os.environ.get("TRIPS_DB")
        if configured_path is None and "TRIPS_FILE" in os.environ:
            raise ValueError(
                "TRIPS_FILE is no longer supported. Set TRIPS_DB and import the JSON "
                "file with python -m app.import_trips PATH_TO_JSON."
            )
        if configured_path is not None and not configured_path.strip():
            raise ValueError("TRIPS_DB must not be empty")
        return cls(configured_path if configured_path is not None else DEFAULT_DATABASE)

    @contextmanager
    def _connection(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            if create:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            mode = "rwc" if create else "rw"
            # Connections belong to one operation/thread. Do not silently create
            # an empty replacement if an initialized database disappears.
            with closing(sqlite3.connect(
                f"{self._path.as_uri()}?mode={mode}",
                uri=True,
                timeout=self._timeout,
                isolation_level=None,
                autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
            )) as connection:
                connection.row_factory = sqlite3.Row
                yield connection
        except (sqlite3.Error, OSError, ValidationError) as exc:
            raise TripStorageError(f"Cannot access trip database: {self._path}") from exc

    def initialize(self) -> None:
        """Create schema version 1, or verify the existing schema version."""
        with self._connection(create=True) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                connection.execute(_CREATE_TABLE)
                connection.execute("PRAGMA user_version = 1")
            elif version != 1:
                raise TripStorageError(f"Unsupported database schema version: {version}")

    def list_trips(self) -> list[Trip]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, start, end, amount, payment, commission FROM trips ORDER BY rowid"
            ).fetchall()
            return [Trip.model_validate(dict(row)) for row in rows]

    @staticmethod
    def _insert(connection: sqlite3.Connection, trip: Trip) -> Trip | None:
        """Insert the trip, or return the existing record on an ID conflict."""
        cursor = connection.execute(_INSERT_TRIP, trip.model_dump(mode="json"))
        if cursor.rowcount == 0:
            row = connection.execute(
                "SELECT id, start, end, amount, payment, commission FROM trips WHERE id = ?",
                (trip.id,),
            ).fetchone()
            return Trip.model_validate(dict(row))
        return None

    def add_trip(self, trip: Trip) -> Trip:
        trip = Trip.model_validate(trip)
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._insert(connection, trip)
            if existing is not None:
                raise DuplicateTripError(existing)
        return trip

    def import_json(self, source: str | Path) -> int:
        """Import all records atomically; skip identical records, reject conflicts."""
        source = Path(source)
        try:
            trips = _trips_adapter.validate_json(source.read_bytes())
        except (OSError, ValidationError) as exc:
            raise TripStorageError(f"Invalid or unreadable import file: {source}") from exc
        ids = [trip.id for trip in trips]
        if len(ids) != len(set(ids)):
            raise TripStorageError(f"Duplicate IDs in import file: {source}")

        imported = 0
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for trip in trips:
                existing = self._insert(connection, trip)
                if existing is None:
                    imported += 1
                elif existing != trip:
                    raise DuplicateTripError(existing)
        return imported
