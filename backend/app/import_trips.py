"""Run with: python -m app.import_trips [JSON_FILE] [--database DATABASE]."""

import argparse
import sys
from pathlib import Path

from app.storage import (
    DEFAULT_IMPORT_FILE,
    DuplicateTripError,
    SqliteTripStore,
    TripStorageError,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import JSON trips into SQLite")
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_IMPORT_FILE)
    parser.add_argument("--database", type=Path, help="Overrides TRIPS_DB")
    args = parser.parse_args(argv)
    try:
        store = (
            SqliteTripStore(args.database)
            if args.database is not None
            else SqliteTripStore.from_environment()
        )
        store.initialize()
        count = store.import_json(args.source)
    except (TripStorageError, DuplicateTripError, ValueError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    print(f"Imported {count} trip(s) into {store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
