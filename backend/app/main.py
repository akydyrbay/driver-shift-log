"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(title="Driver Shift Log API", version="0.1.0")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}
