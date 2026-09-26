from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_EXTRA_QUOTAS = [
    "powGetPvSum",
    "vinPv1",
    "vinPv2",
    "vinPv3",
    "vinPv4",
    "iinPv1",
    "iinPv2",
    "iinPv3",
    "iinPv4",
    "powPv1",
    "powPv2",
    "powPv3",
    "powPv4",
    "pvState1",
    "pvState2",
    "pvState3",
    "pvState4",
    "mpptState1",
    "mpptState2",
    "mpptState3",
    "mpptState4",
]


def _load_secrets() -> dict[str, str]:
    secrets_path = Path(os.getenv("ECOFLOW_SECRETS_FILE", "secrets.yml"))
    if not secrets_path.exists():
        return {}

    secrets: dict[str, str] = {}
    for line_number, line in enumerate(secrets_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ValueError(f"Invalid secrets.yml entry on line {line_number}: expected KEY: value")

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Invalid secrets.yml entry on line {line_number}: missing key")
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        secrets[key] = value

    return secrets


def _get_value(name: str, secrets: dict[str, str]) -> str | None:
    value = os.getenv(name)
    if value is not None:
        return value
    return secrets.get(name)


def _get_required(name: str, secrets: dict[str, str]) -> str:
    value = (_get_value(name, secrets) or "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _get_bool(name: str, default: bool, secrets: dict[str, str]) -> bool:
    value = _get_value(name, secrets)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_csv(name: str, secrets: dict[str, str]) -> list[str]:
    value = _get_value(name, secrets) or ""
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_mqtt_endpoint(secrets: dict[str, str] | None = None) -> tuple[str, int, str | None, str | None]:
    if secrets is None:
        secrets = _load_secrets()
    raw_host = _get_required("MQTT_HOST", secrets)
    default_port = int(_get_value("MQTT_PORT", secrets) or "1883")
    username = _get_value("MQTT_USERNAME", secrets) or None
    password = _get_value("MQTT_PASSWORD", secrets) or None
    if "://" not in raw_host:
        return raw_host, default_port, username, password

    parsed = urlparse(raw_host)
    if not parsed.hostname:
        raise ValueError(f"Invalid MQTT_HOST URL: {raw_host}")
    return (
        parsed.hostname,
        parsed.port or default_port,
        username or parsed.username,
        password or parsed.password,
    )


@dataclass(frozen=True)
class Config:
    ecoflow_access_key: str
    ecoflow_secret_key: str
    ecoflow_api_host: str
    ecoflow_device_sns: list[str]
    ecoflow_quotas: list[str]
    ecoflow_extra_quotas: list[str]
    ecoflow_stream_seconds: int
    poll_interval_seconds: int
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_client_id: str
    mqtt_topic_prefix: str
    mqtt_retain: bool
    mqtt_publish_individual: bool
    mqtt_topic_state_file: str
    health_status_file: str
    healthcheck_max_age_seconds: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        secrets = _load_secrets()
        mqtt_host, mqtt_port, mqtt_username, mqtt_password = _get_mqtt_endpoint(secrets)
        ecoflow_stream_seconds = int(_get_value("ECOFLOW_STREAM_SECONDS", secrets) or "20")
        poll_interval_seconds = int(_get_value("POLL_INTERVAL_SECONDS", secrets) or "60")
        return cls(
            ecoflow_access_key=_get_required("ECOFLOW_ACCESS_KEY", secrets),
            ecoflow_secret_key=_get_required("ECOFLOW_SECRET_KEY", secrets),
            ecoflow_api_host=(_get_value("ECOFLOW_API_HOST", secrets) or "https://api-a.ecoflow.com").rstrip("/"),
            ecoflow_device_sns=_get_csv("ECOFLOW_DEVICE_SNS", secrets),
            ecoflow_quotas=_get_csv("ECOFLOW_QUOTAS", secrets),
            ecoflow_extra_quotas=_get_csv("ECOFLOW_EXTRA_QUOTAS", secrets) or DEFAULT_EXTRA_QUOTAS,
            ecoflow_stream_seconds=ecoflow_stream_seconds,
            poll_interval_seconds=poll_interval_seconds,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            mqtt_username=mqtt_username,
            mqtt_password=mqtt_password,
            mqtt_client_id=_get_value("MQTT_CLIENT_ID", secrets) or "ecoflow-mqtt",
            mqtt_topic_prefix=(_get_value("MQTT_TOPIC_PREFIX", secrets) or "ecoflow").strip("/"),
            mqtt_retain=_get_bool("MQTT_RETAIN", True, secrets),
            mqtt_publish_individual=_get_bool("MQTT_PUBLISH_INDIVIDUAL", True, secrets),
            mqtt_topic_state_file=_get_value("MQTT_TOPIC_STATE_FILE", secrets) or "/tmp/ecoflow-mqtt-topics.json",
            health_status_file=_get_value("HEALTH_STATUS_FILE", secrets) or "/tmp/ecoflow-mqtt-health.json",
            healthcheck_max_age_seconds=int(
                _get_value("HEALTHCHECK_MAX_AGE_SECONDS", secrets)
                or str(max(120, poll_interval_seconds * 2 + ecoflow_stream_seconds + 30))
            ),
            log_level=_get_value("LOG_LEVEL", secrets) or "INFO",
        )
