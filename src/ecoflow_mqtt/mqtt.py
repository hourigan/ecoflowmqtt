from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ecoflow_mqtt.ecoflow import Device


def safe_topic_part(value: str) -> str:
    # Percent encoding keeps distinct source names distinct, including empty names.
    return quote(value, safe="._-") or "%"


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


def _iter_leaf_paths(value: Any, path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_leaf_paths(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_leaf_paths(child, (*path, str(index)))
    else:
        yield path, value


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
        topic_state_file: str | None = None,
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
        self.topic_state_file = Path(topic_state_file) if topic_state_file else None
        self._published_topics_by_device = self._load_topic_state()
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

        messages = {
            f"{base_topic}/state": json.dumps(state, separators=(",", ":"), sort_keys=True),
            f"{base_topic}/online": json.dumps(device.online),
        }

        if self.publish_individual:
            for quota_name, quota_value in quotas.items():
                quota_part = safe_topic_part(str(quota_name))
                topic = f"{base_topic}/quota/{quota_part}"
                messages[topic] = _json_payload(quota_value)
                if isinstance(quota_value, (dict, list)):
                    for path, leaf_value in _iter_leaf_paths(quota_value, (str(quota_name),)):
                        leaf_topic = f"{base_topic}/quota/" + "/".join(safe_topic_part(part) for part in path)
                        messages[leaf_topic] = _json_payload(leaf_value)

        previous = self._published_topics_by_device.get(device.sn, set())
        # Record topics before publishing so a crash cannot leave new retained topics untracked.
        self._published_topics_by_device[device.sn] = previous | messages.keys()
        self._save_topic_state()
        for topic, payload in messages.items():
            self._publish(topic, payload)

        for topic in previous - messages.keys():
            self._clear_retained(topic)
        self._published_topics_by_device[device.sn] = set(messages)
        self._save_topic_state()

    def finish_cycle(self, active_sns: set[str]) -> None:
        for sn in set(self._published_topics_by_device) - active_sns:
            for topic in self._published_topics_by_device[sn]:
                self._clear_retained(topic)
            del self._published_topics_by_device[sn]
            self._save_topic_state()

    def _load_topic_state(self) -> dict[str, set[str]]:
        if self.topic_state_file is None or not self.topic_state_file.exists():
            return {}
        raw = json.loads(self.topic_state_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid MQTT topic state file: {self.topic_state_file}")
        topics_by_device: dict[str, set[str]] = {}
        for sn, topics in raw.items():
            if not isinstance(sn, str) or not isinstance(topics, list) or not all(
                isinstance(topic, str) and topic.startswith(f"{self.topic_prefix}/{safe_topic_part(sn)}/")
                for topic in topics
            ):
                raise ValueError(f"Invalid MQTT topic state file: {self.topic_state_file}")
            topics_by_device[sn] = set(topics)
        return topics_by_device

    def _save_topic_state(self) -> None:
        if self.topic_state_file is None:
            return
        self.topic_state_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.topic_state_file.with_name(f".{self.topic_state_file.name}.tmp")
        state = {sn: sorted(topics) for sn, topics in self._published_topics_by_device.items()}
        temp_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(temp_path, self.topic_state_file)

    def _clear_retained(self, topic: str) -> None:
        result = self.client.publish(topic, payload="", qos=0, retain=True)
        result.wait_for_publish()
        if result.rc != self._mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"Failed to clear retained MQTT topic {topic}: rc={result.rc}")

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
