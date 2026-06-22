from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone

from ecoflow_mqtt.config import Config
from ecoflow_mqtt.ecoflow import EcoFlowClient
from ecoflow_mqtt.health import HealthCheckError, check_health_status, write_health_status
from ecoflow_mqtt.mqtt import MqttPublisher
from ecoflow_mqtt.stream import EcoFlowStreamClient


LOGGER = logging.getLogger(__name__)


class Shutdown:
    requested = False

    def request(self, _signum: int, _frame: object) -> None:
        self.requested = True


def poll_once(config: Config, ecoflow: EcoFlowClient, publisher: MqttPublisher) -> None:
    configured_sns = set(config.ecoflow_device_sns)
    devices = ecoflow.list_devices()
    if configured_sns:
        devices = [device for device in devices if device.sn in configured_sns]

    stream_quotas: dict[str, dict[str, object]] = {}
    if config.ecoflow_stream_seconds > 0 and devices:
        LOGGER.info("Collecting EcoFlow stream quota updates for %s second(s)", config.ecoflow_stream_seconds)
        stream_quotas = EcoFlowStreamClient(ecoflow).collect_quotas(
            [device.sn for device in devices],
            config.ecoflow_stream_seconds,
        )

    LOGGER.info("Polling %s EcoFlow device(s)", len(devices))
    for device in devices:
        if config.ecoflow_quotas:
            quotas = ecoflow.get_quotas(device.sn, config.ecoflow_quotas)
        else:
            quotas = ecoflow.get_all_quotas(device.sn)
            if config.ecoflow_extra_quotas:
                quotas.update(ecoflow.get_quotas(device.sn, config.ecoflow_extra_quotas))
        quotas.update(stream_quotas.get(device.sn, {}))

        timestamp = datetime.now(timezone.utc).isoformat()
        publisher.publish_device_state(device, quotas, timestamp)
        LOGGER.info("Published %s quota value(s) for %s", len(quotas), device.sn)


def run(config: Config, once: bool = False) -> None:
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    shutdown = Shutdown()
    signal.signal(signal.SIGINT, shutdown.request)
    signal.signal(signal.SIGTERM, shutdown.request)

    ecoflow = EcoFlowClient(
        access_key=config.ecoflow_access_key,
        secret_key=config.ecoflow_secret_key,
        api_host=config.ecoflow_api_host,
    )
    publisher = MqttPublisher(
        host=config.mqtt_host,
        port=config.mqtt_port,
        username=config.mqtt_username,
        password=config.mqtt_password,
        client_id=config.mqtt_client_id,
        topic_prefix=config.mqtt_topic_prefix,
        retain=config.mqtt_retain,
        publish_individual=config.mqtt_publish_individual,
    )

    publisher.connect()
    LOGGER.info("Connected to MQTT broker %s:%s", config.mqtt_host, config.mqtt_port)
    try:
        while not shutdown.requested:
            try:
                poll_once(config, ecoflow, publisher)
                write_health_status(config.health_status_file, "ok")
            except Exception:
                LOGGER.exception("Polling cycle failed")
                write_health_status(
                    config.health_status_file,
                    "error",
                    "Last polling cycle failed; inspect container logs for the traceback.",
                )

            if once:
                break

            deadline = time.monotonic() + config.poll_interval_seconds
            while not shutdown.requested and time.monotonic() < deadline:
                time.sleep(0.5)
    finally:
        publisher.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ecoflow-mqtt",
        description="Poll EcoFlow Open Platform devices and publish readings to MQTT.",
    )
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit.")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Validate the application health status file and exit.",
    )
    args = parser.parse_args()
    config = Config.from_env()
    if args.healthcheck:
        try:
            check_health_status(config.health_status_file, config.healthcheck_max_age_seconds)
        except HealthCheckError as exc:
            print(f"unhealthy: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print("healthy")
        return

    run(config, once=args.once)


if __name__ == "__main__":
    main()
