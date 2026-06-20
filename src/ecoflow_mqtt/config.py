from __future__ import annotations

import os
from dataclasses import dataclass
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


def _get_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_csv(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_mqtt_endpoint() -> tuple[str, int, str | None, str | None]:
    raw_host = _get_required("MQTT_HOST")
    default_port = int(os.getenv("MQTT_PORT", "1883"))
    username = os.getenv("MQTT_USERNAME") or None
    password = os.getenv("MQTT_PASSWORD") or None
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
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        mqtt_host, mqtt_port, mqtt_username, mqtt_password = _get_mqtt_endpoint()
        return cls(
            ecoflow_access_key=_get_required("ECOFLOW_ACCESS_KEY"),
            ecoflow_secret_key=_get_required("ECOFLOW_SECRET_KEY"),
            ecoflow_api_host=os.getenv("ECOFLOW_API_HOST", "https://api-a.ecoflow.com").rstrip("/"),
            ecoflow_device_sns=_get_csv("ECOFLOW_DEVICE_SNS"),
            ecoflow_quotas=_get_csv("ECOFLOW_QUOTAS"),
            ecoflow_extra_quotas=_get_csv("ECOFLOW_EXTRA_QUOTAS") or DEFAULT_EXTRA_QUOTAS,
            ecoflow_stream_seconds=int(os.getenv("ECOFLOW_STREAM_SECONDS", "20")),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            mqtt_username=mqtt_username,
            mqtt_password=mqtt_password,
            mqtt_client_id=os.getenv("MQTT_CLIENT_ID", "ecoflow-mqtt"),
            mqtt_topic_prefix=os.getenv("MQTT_TOPIC_PREFIX", "ecoflow").strip("/"),
            mqtt_retain=_get_bool("MQTT_RETAIN", True),
            mqtt_publish_individual=_get_bool("MQTT_PUBLISH_INDIVIDUAL", True),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
