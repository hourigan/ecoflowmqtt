# EcoFlow MQTT

Polls the EcoFlow Open Platform API for devices on your account and publishes device data to an MQTT broker on your local network.

## What It Publishes

For each device, the service publishes:

- `ecoflow/<device_sn>/state`: full JSON payload containing device metadata, all quota values, and a timestamp.
- `ecoflow/<device_sn>/online`: `true` or `false`.
- `ecoflow/<device_sn>/quota/<quota_name>`: individual quota values, when `MQTT_PUBLISH_INDIVIDUAL=true`.
- `ecoflow/<device_sn>/quota/<nested_quota_path>`: nested quota leaf values flattened into sensor-friendly topics.

Quota names are sanitized for MQTT topics by replacing `/`, spaces, and other unsafe characters with `_`.

STREAM MPPT/PV socket data is collected from EcoFlow's cloud MQTT quota stream because the HTTP quota endpoint may only return aggregate PV values. When EcoFlow returns these values, they are published under `quota/...` topics. For STREAM Ultra, useful fields include:

- PV1 voltage fields such as `plugInInfoPvVol` or `vinPv1`.
- PV1 current fields such as `plugInInfoPvAmp` or `iinPv1`.
- PV1 power fields such as `pinPv1`.
- PV2-PV4 fields such as `plugInInfoPv<N>` and `powGetPv<N>` when EcoFlow sends them.

## Setup

Create a virtual environment and install the app:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Create your environment and secrets files:

```bash
cp .env.example .env
cp secrets.yml.example secrets.yml
```

Edit `.env` with normal runtime settings, and `secrets.yml` with your EcoFlow
developer credentials and local MQTT broker credentials.

## Running

```bash
. .venv/bin/activate
set -a
. ./.env
set +a
ecoflow-mqtt
```

Or run the module directly:

```bash
python -m ecoflow_mqtt.app
```

## Docker

Build and run with Docker Compose:

```bash
docker compose up -d --build
```

If your Docker install uses the legacy Compose command:

```bash
docker-compose up -d --build
```

The Compose service loads `.env` as environment variables with `env_file` and
mounts `secrets.yml` read-only at `/app/secrets.yml`. Environment variables take
precedence when a value is present in both places.

To run without Compose:

```bash
docker build -t ecoflow-mqtt .
docker run -d --name ecoflow-mqtt --restart unless-stopped --env-file .env -v "$PWD/secrets.yml:/app/secrets.yml:ro" ecoflow-mqtt
```

View logs:

```bash
docker logs -f ecoflow-mqtt
```

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `ECOFLOW_ACCESS_KEY` | yes | | EcoFlow Open Platform access key. |
| `ECOFLOW_SECRET_KEY` | yes | | EcoFlow Open Platform secret key. |
| `ECOFLOW_API_HOST` | no | `https://api-a.ecoflow.com` | EcoFlow API host. This project is configured for EU accounts with `https://api-e.ecoflow.com`. |
| `ECOFLOW_DEVICE_SNS` | no | all account devices | Comma-separated serial numbers to poll. |
| `ECOFLOW_QUOTAS` | no | all quotas | Comma-separated quota names. When unset, `/device/quota/all` is used. |
| `ECOFLOW_EXTRA_QUOTAS` | no | common STREAM PV/MPPT candidates | Extra comma-separated quota names to request in addition to all quotas. |
| `ECOFLOW_STREAM_SECONDS` | no | `20` | Seconds to collect EcoFlow cloud MQTT stream quota updates each poll. |
| `POLL_INTERVAL_SECONDS` | no | `60` | Seconds between polling cycles. |
| `MQTT_HOST` | yes | | Local MQTT broker hostname or IP. |
| `MQTT_PORT` | no | `1883` | Local MQTT broker port. |
| `MQTT_USERNAME` | no | | Local MQTT username. |
| `MQTT_PASSWORD` | no | | Local MQTT password. |
| `MQTT_CLIENT_ID` | no | `ecoflow-mqtt` | MQTT client ID. |
| `MQTT_TOPIC_PREFIX` | no | `ecoflow` | MQTT topic prefix. |
| `MQTT_RETAIN` | no | `true` | Whether MQTT messages are retained. |
| `MQTT_PUBLISH_INDIVIDUAL` | no | `true` | Publish each quota on its own topic as well as the full JSON state. |
| `LOG_LEVEL` | no | `INFO` | Python logging level. |

## Notes

EcoFlow signs requests with HMAC-SHA256 over sorted request parameters plus `accessKey`, `nonce`, and `timestamp`. This implementation includes a regression test using EcoFlow's published signing example.

The service reads baseline data from EcoFlow over HTTPS, collects richer STREAM telemetry from EcoFlow's cloud MQTT quota stream, and writes normalized sensor topics to your local MQTT broker.

See [docs/ecoflow-fields.md](docs/ecoflow-fields.md) for the observed EcoFlow
API fields, categories, source endpoints, and derived MQTT sensor mappings.
