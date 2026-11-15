# Changelog

## 0.2.0 - 2026-11-15

- MQTT 3.1.1 client in pure Python (`mqtt.py`): QoS 0 and 1, retained last will, reconnect with a growing delay; standard library only.
- Home Assistant MQTT discovery: a switch for each outlet output, and sensors for power, voltage, current, power factor and energy of each outlet.
- MQTT bridge (`bridge.py`): retained states and availability, retained `online` status, and output commands (`output/set` with ON or OFF) queued for the next regular inform of the device.
- MQTT settings (`mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`, `mqtt_topic_prefix`, `mqtt_discovery_prefix`) and the Supervisor MQTT service in add-on mode (`services: mqtt:want`).
- MQTT is optional in standalone mode: without a broker host the bridge does not start.

## 0.1.0 - 2026-11-15

- First version of the phase 2 add-on.
- Pure Python AES-128 and BSON reader.
- Inform packets: decrypt, compressed payloads, same IV in the response.
- Device store `devices.json` with schema 1.
- Import of keys and ports from `.unf` backups.
- Device states (a device is lost after 120 s without an inform).
- `mfi-output` command queue.
- Wake-up packet builder.
- Measurements with energy counter compensation.
- HTTP inform server.
- Command line: `decode` and `import-backup`.
- Never sends a factory reset.
