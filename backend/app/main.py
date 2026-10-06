"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routes import router
from app.storage import SqliteTripStore, TripStorageError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    store = SqliteTripStore.from_environment()
    store.initialize()
    store.list_trips()  # Fail startup if existing records are invalid.
    application.state.trip_store = store
    yield


app = FastAPI(title="Driver Shift Log API", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(TripStorageError)
async def storage_error(request: Request, exc: TripStorageError) -> JSONResponse:
    logger.error("Trip storage is unavailable", exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "Trip storage is unavailable"})


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}
