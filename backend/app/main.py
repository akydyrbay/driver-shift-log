"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes import router
from app.storage import SqliteTripStore, TripStorageError
from app.web import FlutterStaticFiles

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    store = SqliteTripStore.from_environment()
    store.initialize()
    store.list_trips()  # Fail startup if existing records are invalid.
    application.state.trip_store = store
    yield


async def storage_error(request: Request, exc: TripStorageError) -> JSONResponse:
    logger.error("Trip storage is unavailable", exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "Trip storage is unavailable"})


async def health() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    application = FastAPI(title="Driver Shift Log API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(router)
    application.add_exception_handler(TripStorageError, storage_error)
    application.add_api_route("/health", health, tags=["health"])
    web_directory = os.environ.get("WEB_DIR")
    if web_directory is not None:
        if not web_directory.strip():
            raise ValueError("WEB_DIR must not be empty")
        # Mount last: API, health, OpenAPI and documentation keep their routes.
        application.mount("/", FlutterStaticFiles(web_directory), name="web")
    return application


app = create_app()
