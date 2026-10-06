"""JSON storage for a single server process, with atomic file replacement."""

import json
import logging
import os
from _thread import LockType
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from pydantic import TypeAdapter, ValidationError

from app.models import Trip

DEFAULT_TRIPS_FILE = Path(__file__).resolve().parent.parent / "data" / "trips.json"
logger = logging.getLogger(__name__)
_trips_adapter = TypeAdapter(list[Trip])
_locks: dict[Path, LockType] = {}
_locks_guard = Lock()


class TripStorageError(RuntimeError):
    """The trip file could not be read, validated, or saved."""


class DuplicateTripError(ValueError):
    """An existing record already owns this trip ID."""

    def __init__(self, existing: Trip) -> None:
        self.existing = existing
        super().__init__(f"Trip ID already exists: {existing.id}")


class JsonTripStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()
        # Instances pointing to the same file must share the transaction lock.
        with _locks_guard:
            self._lock = _locks.setdefault(self._path, Lock())

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def from_environment(cls) -> "JsonTripStore":
        configured_path = os.environ.get("TRIPS_FILE")
        if configured_path is not None and not configured_path.strip():
            raise ValueError("TRIPS_FILE must not be empty")
        return cls(configured_path if configured_path is not None else DEFAULT_TRIPS_FILE)

    def list_trips(self) -> list[Trip]:
        with self._lock:
            return self._read_unlocked()

    def add_trip(self, trip: Trip) -> Trip:
        trip = Trip.model_validate(trip)
        with self._lock:
            trips = self._read_unlocked()
            for existing in trips:
                if existing.id == trip.id:
                    raise DuplicateTripError(existing)
            trips.append(trip)
            self._write_unlocked(trips)
        return trip

    def _read_unlocked(self) -> list[Trip]:
        try:
            content = self._path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise TripStorageError(f"Cannot read trip file: {self._path}") from exc

        try:
            trips = _trips_adapter.validate_json(content)
        except ValidationError as exc:
            raise TripStorageError(f"Invalid trip file: {self._path}") from exc

        ids = [trip.id for trip in trips]
        if len(ids) != len(set(ids)):
            raise TripStorageError(f"Duplicate IDs in trip file: {self._path}")
        return trips

    def _write_unlocked(self, trips: list[Trip]) -> None:
        temporary_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # The temporary file must be on the same filesystem as the target.
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(
                    [trip.model_dump(mode="json") for trip in trips],
                    temporary,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._path)
            temporary_path = None
        except OSError as exc:
            raise TripStorageError(f"Cannot save trip file: {self._path}") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    # Preserve the write error if cleanup also fails.
                    logger.warning("Cannot remove temporary file: %s", temporary_path)
