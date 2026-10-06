"""Smoke-test a built image in a fresh Compose project; remove only its test data.

Run from any directory: python3 scripts/check_container.py --image driver-shift-log:ci
Requires Docker Compose and Python's standard library, not backend dependencies.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
DAY = "2026-10-01"
EXPECTED = {
    "date": DAY,
    "trip_count": 3,
    "revenue": 4700,
    "commission": 685,
    "take_home": 4015,
    "cash_revenue": 2300,
    "card_revenue": 2400,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="driver-shift-log:ci")
    args = parser.parse_args()
    # Fail before creating resources if the requested image does not exist.
    subprocess.run(["docker", "image", "inspect", args.image], check=True, stdout=subprocess.DEVNULL)
    project = f"driver-shift-ci-{uuid4().hex[:12]}"
    environment = dict(os.environ, APP_PORT="0")  # Random loopback-only host port.
    with TemporaryDirectory(prefix="driver-shift-compose-") as directory:
        override = Path(directory) / "image.json"
        override.write_text(json.dumps({"services": {"app": {
            "image": args.image, "pull_policy": "never",
        }}}), encoding="utf-8")
        command = ["docker", "compose", "--project-name", project,
                   "--file", str(ROOT / "docker-compose.yml"), "--file", str(override)]

        def compose(*arguments: str, capture: bool = False, check: bool = True) -> str:
            result = subprocess.run(command + list(arguments), env=environment, cwd=ROOT,
                                    check=check, text=True, capture_output=capture, timeout=120)
            return result.stdout.strip() if capture else ""

        base = ""

        def request(path: str, data: dict | None = None, method: str | None = None):
            body = json.dumps(data).encode() if data is not None else None
            query = urllib.request.Request(base + path, data=body, method=method,
                                           headers={"Content-Type": "application/json"} if body else {})
            with urllib.request.urlopen(query, timeout=10) as response:
                payload = response.read()
                if payload and "application/json" in response.headers.get("Content-Type", ""):
                    payload = json.loads(payload)
                return response.status, payload

        def start(*extra: str) -> None:
            nonlocal base
            compose("up", "--no-build", "--detach", "--wait", "--wait-timeout", "60", *extra)
            address = compose("port", "app", "8000", capture=True)
            require(address.startswith("127.0.0.1:"), f"Unexpected binding: {address}")
            base = f"http://{address}"

        def check_persistence() -> None:
            require(request(f"/api/summary?date={DAY}")[1] == EXPECTED, "Daily totals changed")
            trips = request(f"/api/trips?date={DAY}")[1]
            require(len(trips) == 3 and any(trip["id"] == "ci-persistence" for trip in trips),
                    "Saved trip did not persist")

        try:
            start()
            require(request("/health")[1] == {"status": "ok"}, "Health check failed")
            require(request(f"/api/trips?date={DAY}")[1] == [], "New database is not empty")
            require(b"flutter_bootstrap.js" in request("/")[1], "Flutter entrypoint missing")
            for path in ["/main.dart.js", "/flutter_bootstrap.js", "/canvaskit/chromium/canvaskit.wasm"]:
                require(request(path, method="HEAD")[0] == 200, f"Missing asset: {path}")
            for path in ["/data/trips.sqlite3", "/app/storage.py", "/api/missing", "/missing.js"]:
                try:
                    request(path)
                except urllib.error.HTTPError as error:
                    require(error.code == 404, f"Unexpected status for {path}: {error.code}")
                else:
                    raise RuntimeError(f"Unexpectedly public path: {path}")

            compose("exec", "-T", "app", "python", "-c",
                    "import os; assert os.getuid() == 10001")
            for _ in range(2):
                compose("exec", "-T", "app", "python", "-m", "app.import_trips", "/app/examples/trips.json")
            require(request(f"/api/summary?date={DAY}")[1]["trip_count"] == 2, "Import created duplicates")
            trip = {"id": "ci-persistence", "start": "2026-10-01T10:00:00+05:00",
                    "end": "2026-10-01T10:20:00+05:00", "amount": 800,
                    "commission": 100, "payment": "cash"}
            require(request("/api/trips", trip)[0] == 201, "Trip was not created")
            require(request("/api/trips", trip)[0] == 200, "Retry was not idempotent")
            check_persistence()
            compose("restart", "app")
            start()
            check_persistence()
            start("--force-recreate")
            check_persistence()
            print("Docker smoke test passed: UI, API, import, retries, restart and recreation.", flush=True)
        except BaseException:
            compose("logs", "--no-color", check=False)
            raise
        finally:
            # The random project name is generated here, never supplied by callers.
            compose("down", "--volumes", "--remove-orphans")
            print(f"Removed disposable test resources for {project}.", flush=True)


if __name__ == "__main__":
    main()
