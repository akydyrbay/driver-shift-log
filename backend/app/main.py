"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.storage import JsonTripStore


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    store = JsonTripStore.from_environment()
    store.list_trips()  # Fail startup if an existing data file is invalid.
    application.state.trip_store = store
    yield


app = FastAPI(title="Driver Shift Log API", version="0.1.0", lifespan=lifespan)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}
