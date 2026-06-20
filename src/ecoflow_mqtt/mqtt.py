from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from typing import Any

from ecoflow_mqtt.ecoflow import Device


_UNSAFE_TOPIC_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_topic_part(value: str) -> str:
    return _UNSAFE_TOPIC_CHARS.sub("_", value).strip("_") or "value"


def iter_leaf_values(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from iter_leaf_values(child, child_prefix)
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            child_prefix = f"{prefix}.{index}" if prefix else str(index)
            yield from iter_leaf_values(child, child_prefix)
        return

    if prefix:
        yield prefix, value


def _json_payload(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


class MqttPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        topic_prefix: str,
        username: str | None = None,
        password: str | None = None,
        retain: bool = True,
        publish_individual: bool = True,
    ) -> None:
        import paho.mqtt.client as mqtt

        self.host = host
        self.port = port
        self.topic_prefix = topic_prefix.strip("/")
        self.retain = retain
        self.publish_individual = publish_individual
        self._mqtt = mqtt
        self._connected = threading.Event()
        self._connect_error: str | None = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        if username:
            self.client.username_pw_set(username, password)

    def connect(self) -> None:
        self.client.connect(self.host, self.port)
        self.client.loop_start()
        if not self._connected.wait(timeout=10):
            detail = f": {self._connect_error}" if self._connect_error else ""
            raise TimeoutError(f"Timed out connecting to MQTT broker {self.host}:{self.port}{detail}")

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish_device_state(self, device: Device, quotas: dict[str, Any], timestamp: str) -> None:
        base_topic = f"{self.topic_prefix}/{safe_topic_part(device.sn)}"
        state = {
            "sn": device.sn,
            "deviceName": device.device_name,
            "online": device.online,
            "timestamp": timestamp,
            "quotas": quotas,
            "device": device.raw,
        }

        self._publish(f"{base_topic}/state", json.dumps(state, separators=(",", ":"), sort_keys=True))
        self._publish(f"{base_topic}/online", json.dumps(device.online))

        if self.publish_individual:
            for quota_name, quota_value in quotas.items():
                topic = f"{base_topic}/quota/{safe_topic_part(str(quota_name))}"
                self._publish(topic, _json_payload(quota_value))
                if isinstance(quota_value, (dict, list)):
                    for leaf_name, leaf_value in iter_leaf_values(quota_value, str(quota_name)):
                        leaf_topic = f"{base_topic}/quota/{safe_topic_part(leaf_name)}"
                        self._publish(leaf_topic, _json_payload(leaf_value))

    def _publish(self, topic: str, payload: str) -> None:
        result = self.client.publish(topic, payload=payload, qos=0, retain=self.retain)
        result.wait_for_publish()
        if result.rc != self._mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"Failed to publish MQTT message to {topic}: rc={result.rc}")

    def _on_connect(
        self,
        _client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        is_failure = getattr(reason_code, "is_failure", None)
        if is_failure is not None:
            connected = not bool(is_failure)
        else:
            connected = reason_code == 0 or str(reason_code).lower() in {"0", "success"}

        if connected:
            self._connected.set()
            return
        self._connect_error = str(reason_code)

    def _on_disconnect(
        self,
        _client: Any,
        _userdata: Any,
        _flags: Any,
        _reason_code: Any,
        _properties: Any,
    ) -> None:
        self._connected.clear()
