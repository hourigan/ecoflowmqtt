import json
import os
import time
from types import SimpleNamespace

import pytest

from ecoflow_mqtt import app
from ecoflow_mqtt import stream
from ecoflow_mqtt.config import Config, _get_mqtt_endpoint
from ecoflow_mqtt.ecoflow import Device, flatten_params, sign_request, signature_payload
from ecoflow_mqtt.health import HealthCheckError, check_health_status, write_health_status
from ecoflow_mqtt.mqtt import MqttPublisher, iter_leaf_values, safe_topic_part
from ecoflow_mqtt.stream import EcoFlowStreamClient


def test_signature_matches_ecoflow_documentation_example() -> None:
    params = {
        "sn": "123456789",
        "params": {
            "cmdSet": 11,
            "id": 24,
            "eps": 0,
        },
    }

    assert (
        signature_payload(
            params,
            access_key="Fp4SvIprYSDPXtYJidEtUAd1o",
            nonce=345164,
            timestamp=1671171709428,
        )
        == "params.cmdSet=11&params.eps=0&params.id=24&sn=123456789&accessKey=Fp4SvIprYSDPXtYJidEtUAd1o&nonce=345164&timestamp=1671171709428"
    )
    assert (
        sign_request(
            params,
            access_key="Fp4SvIprYSDPXtYJidEtUAd1o",
            secret_key="WIbFEKre0s6sLnh4ei7SPUeYnptHG6V",
            nonce=345164,
            timestamp=1671171709428,
        )
        == "07c13b65e037faf3b153d51613638fa80003c4c38d2407379a7f52851af1473e"
    )


def test_flatten_params_handles_arrays_and_nested_objects() -> None:
    assert flatten_params({"ids": [1, 2], "deviceInfo": {"id": 3}}) == {
        "ids[0]": "1",
        "ids[1]": "2",
        "deviceInfo.id": "3",
    }


def test_safe_topic_part_encodes_mqtt_unfriendly_characters() -> None:
    assert safe_topic_part("bmsMaster.outputWatts") == "bmsMaster.outputWatts"
    assert safe_topic_part("weird/name + value") == "weird%2Fname%20%2B%20value"
    assert safe_topic_part("a/b") != safe_topic_part("a b")
    assert safe_topic_part("") != safe_topic_part("%")


def test_mqtt_endpoint_parses_url_credentials() -> None:
    old_values = {
        key: os.environ.get(key)
        for key in ("MQTT_HOST", "MQTT_PORT", "MQTT_USERNAME", "MQTT_PASSWORD")
    }
    try:
        os.environ["MQTT_HOST"] = "mqtt://user:pass@mqtt.dockerapp.net:1883"
        os.environ.pop("MQTT_USERNAME", None)
        os.environ.pop("MQTT_PASSWORD", None)
        assert _get_mqtt_endpoint({}) == ("mqtt.dockerapp.net", 1883, "user", "pass")
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_config_loads_credentials_from_secrets_yml(monkeypatch, tmp_path) -> None:
    secrets_file = tmp_path / "secrets.yml"
    secrets_file.write_text(
        "\n".join(
            [
                'ECOFLOW_ACCESS_KEY: "access-from-file"',
                'ECOFLOW_SECRET_KEY: "secret-from-file"',
                'MQTT_USERNAME: "mqtt-user"',
                'MQTT_PASSWORD: "mqtt-pass"',
            ]
        ),
        encoding="utf-8",
    )

    for key in (
        "ECOFLOW_ACCESS_KEY",
        "ECOFLOW_SECRET_KEY",
        "ECOFLOW_API_HOST",
        "ECOFLOW_DEVICE_SNS",
        "ECOFLOW_QUOTAS",
        "ECOFLOW_EXTRA_QUOTAS",
        "ECOFLOW_STREAM_SECONDS",
        "POLL_INTERVAL_SECONDS",
        "MQTT_PORT",
        "MQTT_USERNAME",
        "MQTT_PASSWORD",
        "MQTT_CLIENT_ID",
        "MQTT_TOPIC_PREFIX",
        "MQTT_RETAIN",
        "MQTT_PUBLISH_INDIVIDUAL",
        "HEALTH_STATUS_FILE",
        "HEALTHCHECK_MAX_AGE_SECONDS",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("ECOFLOW_SECRETS_FILE", str(secrets_file))
    monkeypatch.setenv("MQTT_HOST", "mqtt.example.net")

    config = Config.from_env()

    assert config.ecoflow_access_key == "access-from-file"
    assert config.ecoflow_secret_key == "secret-from-file"
    assert config.mqtt_username == "mqtt-user"
    assert config.mqtt_password == "mqtt-pass"
    assert config.health_status_file == "/tmp/ecoflow-mqtt-health.json"
    assert config.healthcheck_max_age_seconds == 170


def test_health_check_accepts_recent_success(tmp_path) -> None:
    status_file = tmp_path / "health.json"

    write_health_status(str(status_file), "ok")

    check_health_status(str(status_file), max_age_seconds=30)


def test_health_check_rejects_recorded_error(tmp_path) -> None:
    status_file = tmp_path / "health.json"

    write_health_status(str(status_file), "error", "poll failed")

    try:
        check_health_status(str(status_file), max_age_seconds=30)
    except HealthCheckError as exc:
        assert "poll failed" in str(exc)
    else:
        raise AssertionError("expected health check to fail")


def test_health_check_rejects_stale_success(tmp_path) -> None:
    status_file = tmp_path / "health.json"
    write_health_status(str(status_file), "ok")
    payload = json.loads(status_file.read_text(encoding="utf-8"))
    payload["updated_at_epoch"] = time.time() - 120
    status_file.write_text(json.dumps(payload), encoding="utf-8")

    try:
        check_health_status(str(status_file), max_age_seconds=30)
    except HealthCheckError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("expected health check to fail")


def test_iter_leaf_values_flattens_nested_quota_data() -> None:
    assert list(iter_leaf_values({"outer": {"inner": 7}, "items": [True]})) == [
        ("outer.inner", 7),
        ("items.0", True),
    ]


def test_publisher_only_publishes_raw_quota_topics() -> None:
    device = Device(
        sn="BK11ZE1B2H542834",
        device_name="STREAM Ultra-2834",
        online=True,
        raw={},
    )
    publisher = MqttPublisher.__new__(MqttPublisher)
    publisher.topic_prefix = "ecoflow"
    publisher.publish_individual = True
    publisher._published_topics_by_device = {}
    publisher.topic_state_file = None
    published: list[tuple[str, str]] = []
    publisher._publish = lambda topic, payload: published.append((topic, payload))

    publisher.publish_device_state(
        device,
        {
            "cmsBattSoc": 41,
            "powGetBpCms": -75.0,
            "vinPv1": 287,
            "iinPv1": 1488,
        },
        "2026-06-12T00:00:00+00:00",
    )

    topics = [topic for topic, _payload in published]
    assert "ecoflow/BK11ZE1B2H542834/quota/cmsBattSoc" in topics
    assert "ecoflow/BK11ZE1B2H542834/quota/powGetBpCms" in topics
    assert "ecoflow/BK11ZE1B2H542834/quota/vinPv1" in topics
    assert not any("/battery/" in topic for topic in topics)
    assert not any("/mppt/" in topic for topic in topics)


def test_publisher_clears_disappearing_retained_topics() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str, bool]] = []

        def publish(self, topic, payload, qos, retain):
            self.messages.append((topic, payload, retain))
            return SimpleNamespace(rc=0, wait_for_publish=lambda: None)

    device = Device("SN", "Device", True, {})
    publisher = MqttPublisher.__new__(MqttPublisher)
    publisher.topic_prefix = "ecoflow"
    publisher.publish_individual = True
    publisher.retain = True
    publisher._published_topics_by_device = {}
    publisher.topic_state_file = None
    publisher.client = FakeClient()
    publisher._mqtt = SimpleNamespace(MQTT_ERR_SUCCESS=0)

    publisher.publish_device_state(device, {"old": 1, "current": 2}, "first")
    publisher.publish_device_state(device, {"current": 3}, "second")
    assert ("ecoflow/SN/quota/old", "", True) in publisher.client.messages

    publisher.finish_cycle(set())
    assert ("ecoflow/SN/online", "", True) in publisher.client.messages
    assert ("ecoflow/SN/quota/current", "", True) in publisher.client.messages


def test_publisher_uses_distinct_topics_for_flat_and_nested_keys() -> None:
    publisher = MqttPublisher.__new__(MqttPublisher)
    publisher.topic_prefix = "ecoflow"
    publisher.publish_individual = True
    publisher._published_topics_by_device = {}
    publisher.topic_state_file = None
    sent: list[str] = []
    publisher._publish = lambda topic, payload: sent.append(topic)
    publisher.publish_device_state(Device("SN", None, True, {}), {"a.b": 1, "a": {"b": 2}}, "now")

    assert "ecoflow/SN/quota/a.b" in sent
    assert "ecoflow/SN/quota/a/b" in sent


def test_poll_continues_with_http_quotas_when_stream_fails(monkeypatch) -> None:
    device = Device("SN", None, True, {})
    ecoflow = SimpleNamespace(list_devices=lambda: [device], get_all_quotas=lambda sn: {"soc": 45})
    published: list[dict] = []
    publisher = SimpleNamespace(
        publish_device_state=lambda _device, quotas, _timestamp: published.append(quotas),
        finish_cycle=lambda _sns: None,
    )
    config = SimpleNamespace(
        ecoflow_device_sns=[], ecoflow_stream_seconds=1, ecoflow_quotas=[], ecoflow_extra_quotas=[]
    )

    def fail_stream(self, sns, seconds):
        raise RuntimeError("stream unavailable")

    monkeypatch.setattr(app.EcoFlowStreamClient, "collect_quotas", fail_stream)
    app.poll_once(config, ecoflow, publisher)

    assert published == [{"soc": 45}]


def test_publisher_restores_topic_inventory_after_restart(tmp_path) -> None:
    state_file = tmp_path / "topics.json"
    device = Device("SN", None, True, {})

    def new_publisher():
        publisher = MqttPublisher(
            host="localhost", port=1883, client_id="test", topic_prefix="ecoflow",
            topic_state_file=str(state_file),
        )
        messages = []

        def publish(topic, payload, qos, retain):
            messages.append((topic, payload, retain))
            return SimpleNamespace(rc=0, wait_for_publish=lambda: None)

        publisher.client.publish = publish
        return publisher, messages

    first, _ = new_publisher()
    first.publish_device_state(device, {"removed": 1}, "first")
    second, messages = new_publisher()
    second.publish_device_state(device, {}, "second")

    assert ("ecoflow/SN/quota/removed", "", True) in messages


def test_stream_rejected_connection_raises(monkeypatch) -> None:
    import paho.mqtt.client as mqtt

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.on_connect = None
            self.on_message = None

        def username_pw_set(self, *args):
            pass

        def tls_set(self, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def loop_start(self):
            self.on_connect(self, None, None, 1, None)

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

    monkeypatch.setattr(mqtt, "Client", FakeClient)
    ecoflow = SimpleNamespace(get_certification=lambda: {
        "certificateAccount": "account", "certificatePassword": "password",
        "url": "example.invalid", "port": 8883,
    })
    with pytest.raises(RuntimeError, match="connection rejected"):
        EcoFlowStreamClient(ecoflow).collect_quotas(["SN"], 1)


def test_stream_rejected_subscription_raises(monkeypatch) -> None:
    import paho.mqtt.client as mqtt

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.on_connect = None
            self.on_subscribe = None

        def username_pw_set(self, *args):
            pass

        def tls_set(self, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def subscribe(self, topic):
            return mqtt.MQTT_ERR_SUCCESS, 1

        def loop_start(self):
            self.on_connect(self, None, None, 0, None)
            self.on_subscribe(self, None, 1, [SimpleNamespace(is_failure=True)], None)

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

    monkeypatch.setattr(mqtt, "Client", FakeClient)
    ecoflow = SimpleNamespace(get_certification=lambda: {
        "certificateAccount": "account", "certificatePassword": "password",
        "url": "example.invalid", "port": 8883,
    })
    with pytest.raises(RuntimeError, match="subscription rejected"):
        EcoFlowStreamClient(ecoflow).collect_quotas(["SN"], 1)


def test_stream_collects_after_subscription_acknowledgment(monkeypatch) -> None:
    import paho.mqtt.client as mqtt

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.on_connect = None
            self.on_subscribe = None
            self.on_message = None

        def username_pw_set(self, *args):
            pass

        def tls_set(self, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def subscribe(self, topic):
            return mqtt.MQTT_ERR_SUCCESS, 1

        def loop_start(self):
            self.on_connect(self, None, None, 0, None)
            self.on_subscribe(self, None, 1, [SimpleNamespace(is_failure=False)], None)
            self.on_message(self, None, SimpleNamespace(
                topic="/open/account/SN/quota", payload=b'{"soc":45}',
            ))

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

    monkeypatch.setattr(mqtt, "Client", FakeClient)
    monkeypatch.setattr(stream.time, "sleep", lambda _seconds: None)
    ecoflow = SimpleNamespace(get_certification=lambda: {
        "certificateAccount": "account", "certificatePassword": "password",
        "url": "example.invalid", "port": 8883,
    })
    assert EcoFlowStreamClient(ecoflow).collect_quotas(["SN"], 1) == {"SN": {"soc": 45}}


def test_once_run_raises_after_recording_failed_health(monkeypatch) -> None:
    class FakePublisher:
        def __init__(self, **kwargs):
            pass

        def connect(self):
            pass

        def disconnect(self):
            pass

    config = SimpleNamespace(
        log_level="INFO", ecoflow_access_key="access", ecoflow_secret_key="secret",
        ecoflow_api_host="https://example.invalid", mqtt_host="localhost", mqtt_port=1883,
        mqtt_username=None, mqtt_password=None, mqtt_client_id="test", mqtt_topic_prefix="ecoflow",
        mqtt_retain=True, mqtt_publish_individual=True, health_status_file="unused",
        mqtt_topic_state_file="unused",
    )
    statuses = []
    monkeypatch.setattr(app, "MqttPublisher", FakePublisher)
    monkeypatch.setattr(app, "EcoFlowClient", lambda **kwargs: object())
    monkeypatch.setattr(app, "poll_once", lambda *args: (_ for _ in ()).throw(RuntimeError("poll failed")))
    monkeypatch.setattr(app, "write_health_status", lambda _path, status, *args: statuses.append(status))
    monkeypatch.setattr(app.signal, "signal", lambda *args: None)

    with pytest.raises(RuntimeError, match="poll failed"):
        app.run(config, once=True)
    assert statuses == ["error"]
