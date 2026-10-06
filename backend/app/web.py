"""Serve only the compiled Flutter directory, never application data."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class FlutterStaticFiles(StaticFiles):
    def __init__(self, directory: str | Path) -> None:
        directory = Path(directory).resolve()
        if not (directory / "index.html").is_file():
            raise ValueError(f"WEB_DIR must contain a Flutter build with index.html: {directory}")
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Unknown API paths must stay API 404s, even if an asset has that name.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        response = await super().get_response(path, scope)
        # Flutter's entrypoint and asset names are stable across releases.
        # Revalidate them rather than serving a stale client after an upgrade.
        response.headers["Cache-Control"] = "no-cache"
        return response
