import os

from ecoflow_mqtt.config import Config, _get_mqtt_endpoint
from ecoflow_mqtt.ecoflow import Device, flatten_params, sign_request, signature_payload
from ecoflow_mqtt.mqtt import MqttPublisher, iter_leaf_values, safe_topic_part


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


def test_safe_topic_part_replaces_mqtt_unfriendly_characters() -> None:
    assert safe_topic_part("bmsMaster.outputWatts") == "bmsMaster.outputWatts"
    assert safe_topic_part("weird/name + value") == "weird_name_value"


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
