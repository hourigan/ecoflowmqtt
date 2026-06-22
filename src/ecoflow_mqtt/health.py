from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


class HealthCheckError(RuntimeError):
    """Raised when the app's health status is missing, stale, or failed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_health_status(path: str, status: str, detail: str | None = None) -> None:
    status_path = Path(path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "updated_at": _utc_now(),
        "updated_at_epoch": time.time(),
    }
    if detail:
        payload["detail"] = detail

    temp_path = status_path.with_name(f".{status_path.name}.tmp")
    temp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, status_path)


def check_health_status(path: str, max_age_seconds: int) -> None:
    status_path = Path(path)
    if not status_path.exists():
        raise HealthCheckError(f"Health status file does not exist: {status_path}")

    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HealthCheckError(f"Health status file is invalid JSON: {exc}") from exc

    status = payload.get("status")
    detail = payload.get("detail")
    if status != "ok":
        message = f"Application status is {status or 'unknown'}"
        if detail:
            message = f"{message}: {detail}"
        raise HealthCheckError(message)

    updated_at_epoch = payload.get("updated_at_epoch")
    if not isinstance(updated_at_epoch, (int, float)):
        raise HealthCheckError("Health status file is missing updated_at_epoch")

    age_seconds = time.time() - updated_at_epoch
    if age_seconds > max_age_seconds:
        raise HealthCheckError(
            f"Last successful poll is stale: {age_seconds:.0f}s old "
            f"(max {max_age_seconds}s)"
        )
