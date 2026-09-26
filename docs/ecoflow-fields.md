# EcoFlow Field Reference

This reference is based on a live EcoFlow Open Platform snapshot collected on
2026-06-09 from one online `STREAM Ultra` device. EcoFlow quota fields are
device- and firmware-specific, so treat this as the observed field set for this
installation rather than a complete EcoFlow schema.

The snapshot used three inputs:

- Device metadata from `/iot-open/sign/device/list`.
- Baseline quota data from `/iot-open/sign/device/quota/all`.
- Short-lived cloud MQTT quota updates from `/open/<account>/<sn>/quota`.

Serial numbers and credentials are intentionally omitted from this document.

## MQTT Topic Mapping

The bridge publishes the full combined payload to:

| Topic | Payload |
| --- | --- |
| `ecoflow/<device_sn>/state` | JSON object containing device metadata, quota values, and timestamp. |
| `ecoflow/<device_sn>/online` | Device online state as JSON boolean. |
| `ecoflow/<device_sn>/quota/<field>` | Individual quota value when `MQTT_PUBLISH_INDIVIDUAL=true`. |

Quota names are percent encoded, with nested object keys separated by `/`.
The nested `energyStrategyOperateMode` field publishes as:

```text
ecoflow/<device_sn>/quota/energyStrategyOperateMode/operateSelfPoweredOpen
```

## Device Metadata

| Field | Type | Source | Category | Meaning |
| --- | --- | --- | --- | --- |
| `sn` | string | Device list | Identity | Device serial number. Used as the MQTT device topic segment after sanitizing. |
| `deviceName` | string | Device list | Identity | Friendly EcoFlow device name. Observed value: `STREAM Ultra-2834`. |
| `online` | integer | Device list | Connectivity | EcoFlow online flag. The app converts `1` to `true` and anything else to `false`. |

## Observed Quota Fields

| Field | Type | Source | Category | Unit | Meaning |
| --- | --- | --- | --- | --- | --- |
| `cmsBattSoc` | float | HTTP quota | Battery | `%` | Current battery state of charge. |
| `cmsMaxChgSoc` | integer | HTTP quota | Battery | `%` | Configured maximum charge limit. |
| `cmsMinDsgSoc` | integer | HTTP quota | Battery | `%` | Configured minimum discharge limit. |
| `backupReverseSoc` | integer | HTTP quota | Battery | `%` | Backup reserve threshold. |
| `powGetBpCms` | float | HTTP quota | Battery power | `W` | Signed battery power reported by the CMS/BP path. Positive values indicate charging; negative values indicate discharging. |
| `bmsDsgRemTime` | integer | Cloud stream | Battery runtime | likely minutes | BMS discharge remaining time estimate. Observed only from the cloud MQTT stream. |
| `cmsDsgRemTime` | integer | Cloud stream | Battery runtime | likely minutes | CMS discharge remaining time estimate. Observed only from the cloud MQTT stream. |
| `powGetPvSum` | float | HTTP quota, requested extra quota | Solar/PV | `W` | Aggregate PV input power. No per-socket PV voltage/current fields were present in this snapshot. |
| `gridConnectionPower` | float | HTTP quota | Grid | `W` | Grid connection power. Observed at `0.0` in the snapshot. |
| `powGetSysGrid` | float | HTTP quota | Grid | `W` | Power associated with the grid side of the system. |
| `feedGridMode` | integer | HTTP quota | Grid/settings | enum | Grid export/feed mode. Values need more samples before assigning labels. |
| `powGetSysLoad` | float | HTTP quota | Load | `W` | System load power. In the snapshot it matched `powGetSysGrid`. |
| `relay2Onoff` | boolean | HTTP quota | Relay/output | on/off | Relay 2 state. |
| `relay3Onoff` | boolean | HTTP quota | Relay/output | on/off | Relay 3 state. |
| `energyStrategyOperateMode.operateSelfPoweredOpen` | boolean | HTTP quota | Energy strategy | on/off | Whether self-powered operating mode is enabled. |
| `energyStrategyOperateMode.operateIntelligentScheduleModeOpen` | boolean | HTTP quota | Energy strategy | on/off | Whether intelligent schedule mode is enabled. |
| `quota_cloud_ts` | string | HTTP quota | Telemetry metadata | timestamp | EcoFlow cloud quota timestamp. Observed format: `YYYY-MM-DD HH:MM:SS`. |

## Categories

### Battery

Battery fields describe state of charge, configured charge/discharge bounds,
reserve threshold, signed pack power, and runtime estimates. They publish under
`quota/...` topics, for example `quota/cmsBattSoc` and `quota/powGetBpCms`.

### Solar/PV and MPPT

The observed HTTP quota set included only aggregate PV input power:

- `powGetPvSum`

Per-socket fields such as `vinPv1`, `iinPv1`, `pinPv1`, `plugInInfoPvVol`,
`plugInInfoPvAmp`, `plugInInfoPv2Vol`, `plugInInfoPv2Amp`, or `powGetPv2`
publish as raw `quota/...` topics when EcoFlow emits them.

### Grid, Load, and Relays

Grid/load fields describe current power flow and operating mode:

- `powGetSysGrid`
- `gridConnectionPower`
- `powGetSysLoad`
- `feedGridMode`

Relay fields expose boolean output states:

- `relay2Onoff`
- `relay3Onoff`

The snapshot is not enough to decode `feedGridMode` enum values. Keep future
samples with known UI settings to build a reliable value map.

### Energy Strategy

Energy strategy fields are mode toggles:

- `energyStrategyOperateMode.operateSelfPoweredOpen`
- `energyStrategyOperateMode.operateIntelligentScheduleModeOpen`

Both were `false` in the observed snapshot.

### Telemetry Metadata

`quota_cloud_ts` is the EcoFlow cloud timestamp for the quota payload. The app
also adds its own UTC `timestamp` to the published `state` payload, so consumers
can compare EcoFlow's reported data time with the local bridge publish time.

## Fields To Watch For

The default `ECOFLOW_EXTRA_QUOTAS` list asks EcoFlow for common STREAM PV/MPPT
candidates that were not returned in this sample:

- `vinPv1` through `vinPv4`
- `iinPv1` through `iinPv4`
- `powPv1` through `powPv4`
- `pvState1` through `pvState4`
- `mpptState1` through `mpptState4`

If these begin appearing during solar production or under different operating
states, update this reference with observed units and value ranges.
