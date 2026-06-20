from __future__ import annotations

import hashlib
import hmac
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


JsonValue = Any


class EcoFlowError(RuntimeError):
    """Raised when EcoFlow returns an unsuccessful response."""


def flatten_params(value: JsonValue, prefix: str | None = None) -> dict[str, str]:
    flattened: dict[str, str] = {}

    if isinstance(value, Mapping):
        for key, child in value.items():
            child_key = str(key) if prefix is None else f"{prefix}.{key}"
            flattened.update(flatten_params(child, child_key))
        return flattened

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            if prefix is None:
                child_key = f"[{index}]"
            else:
                child_key = f"{prefix}[{index}]"
            flattened.update(flatten_params(child, child_key))
        return flattened

    if prefix is None:
        raise ValueError("Cannot flatten a scalar value without a key")

    if isinstance(value, bool):
        flattened[prefix] = "true" if value else "false"
    elif value is None:
        flattened[prefix] = ""
    else:
        flattened[prefix] = str(value)
    return flattened


def signature_payload(
    params: Mapping[str, JsonValue] | None,
    access_key: str,
    nonce: int,
    timestamp: int,
) -> str:
    flattened = flatten_params(params or {})
    parts = [f"{key}={flattened[key]}" for key in sorted(flattened)]
    parts.extend(
        [
            f"accessKey={access_key}",
            f"nonce={nonce}",
            f"timestamp={timestamp}",
        ]
    )
    return "&".join(parts)


def sign_request(
    params: Mapping[str, JsonValue] | None,
    access_key: str,
    secret_key: str,
    nonce: int,
    timestamp: int,
) -> str:
    payload = signature_payload(params, access_key, nonce, timestamp)
    digest = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


@dataclass(frozen=True)
class Device:
    sn: str
    device_name: str | None
    online: bool
    raw: dict[str, Any]


class EcoFlowClient:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        api_host: str = "https://api-a.ecoflow.com",
        timeout_seconds: int = 30,
    ) -> None:
        import requests

        self.access_key = access_key
        self.secret_key = secret_key
        self.api_host = api_host.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def list_devices(self) -> list[Device]:
        data = self._request("GET", "/iot-open/sign/device/list")
        return [
            Device(
                sn=str(item["sn"]),
                device_name=item.get("deviceName"),
                online=str(item.get("online", "0")) == "1",
                raw=item,
            )
            for item in data.get("data", [])
            if item.get("sn")
        ]

    def get_all_quotas(self, sn: str) -> dict[str, Any]:
        data = self._request("GET", "/iot-open/sign/device/quota/all", query={"sn": sn})
        return data.get("data") or {}

    def get_quotas(self, sn: str, quotas: list[str]) -> dict[str, Any]:
        body: dict[str, Any] = {"sn": sn, "params": {"quotas": quotas}}
        data = self._request("POST", "/iot-open/sign/device/quota", body=body)
        return data.get("data") or {}

    def get_certification(self) -> dict[str, Any]:
        data = self._request("GET", "/iot-open/sign/certification")
        return data.get("data") or {}

    def _request(
        self,
        method: str,
        path: str,
        query: Mapping[str, JsonValue] | None = None,
        body: Mapping[str, JsonValue] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        sign_params = body if body is not None else query
        headers = self._auth_headers(sign_params)

        if body is not None:
            headers["Content-Type"] = "application/json;charset=UTF-8"

        response = self.session.request(
            method,
            f"{self.api_host}{path}",
            params=query,
            json=body,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        if str(payload.get("code")) != "0":
            message = payload.get("message") or "unknown EcoFlow API error"
            raise EcoFlowError(f"EcoFlow API returned code {payload.get('code')}: {message}")

        return payload

    def _auth_headers(self, params: Mapping[str, JsonValue] | None) -> dict[str, str]:
        nonce = random.randint(100000, 999999)
        timestamp = int(time.time() * 1000)
        return {
            "accessKey": self.access_key,
            "nonce": str(nonce),
            "timestamp": str(timestamp),
            "sign": sign_request(params, self.access_key, self.secret_key, nonce, timestamp),
        }
