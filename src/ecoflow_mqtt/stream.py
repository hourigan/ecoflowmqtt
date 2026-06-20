from __future__ import annotations

import json
import ssl
import threading
import time
from typing import Any

from ecoflow_mqtt.ecoflow import EcoFlowClient


class EcoFlowStreamClient:
    def __init__(self, ecoflow: EcoFlowClient) -> None:
        self.ecoflow = ecoflow

    def collect_quotas(self, sns: list[str], seconds: int) -> dict[str, dict[str, Any]]:
        if seconds <= 0 or not sns:
            return {}

        import paho.mqtt.client as mqtt

        certification = self.ecoflow.get_certification()
        account = certification["certificateAccount"]
        password = certification["certificatePassword"]
        host = certification["url"]
        port = int(certification.get("port") or 8883)
        protocol = str(certification.get("protocol") or "").lower()

        collected: dict[str, dict[str, Any]] = {sn: {} for sn in sns}
        connected = threading.Event()
        lock = threading.Lock()

        def on_connect(client: Any, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
            if str(reason_code).lower() not in {"0", "success"} and getattr(reason_code, "is_failure", False):
                return
            for sn in sns:
                client.subscribe(f"/open/{account}/{sn}/quota")
            connected.set()

        def on_message(_client: Any, _userdata: Any, message: Any) -> None:
            try:
                payload = json.loads(message.payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return

            parts = message.topic.strip("/").split("/")
            if len(parts) < 4:
                return
            sn = parts[2]
            if sn not in collected or not isinstance(payload, dict):
                return

            with lock:
                collected[sn].update(payload)

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ecoflow-mqtt-stream")
        client.on_connect = on_connect
        client.on_message = on_message
        client.username_pw_set(account, password)
        if protocol == "mqtts" or port == 8883:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        client.connect(host, port, keepalive=30)
        client.loop_start()
        try:
            connected.wait(timeout=10)
            time.sleep(seconds)
        finally:
            client.loop_stop()
            client.disconnect()

        return collected
