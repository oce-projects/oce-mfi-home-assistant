"""Home Assistant MQTT discovery messages of mfi-server.

Pure functions, no I/O, standard library only. Each message is a pair
(topic, config); the bridge publishes the config as retained JSON. A relay
(tag output) becomes a switch, every other tag becomes a sensor.
"""
from __future__ import annotations

DEFAULT_POWER_TAGS = ("output", "active_pwr", "v_rms", "i_rms", "pf", "energy_sum")

QUANTITY_NAME = {
    "output": "Output",
    "active_pwr": "Power",
    "v_rms": "Voltage",
    "i_rms": "Current",
    "pf": "Power Factor",
    "energy_sum": "Energy",
}

SENSOR_FIELDS = {
    "active_pwr": {"device_class": "power", "unit_of_measurement": "W", "state_class": "measurement"},
    "v_rms": {"device_class": "voltage", "unit_of_measurement": "V", "state_class": "measurement"},
    "i_rms": {"device_class": "current", "unit_of_measurement": "A", "state_class": "measurement"},
    "pf": {"device_class": "power_factor", "state_class": "measurement"},
    "energy_sum": {"device_class": "energy", "unit_of_measurement": "Wh", "state_class": "total_increasing"},
}


def discovery_messages(device: dict, discovery_prefix: str, topic_prefix: str) -> list[tuple[str, dict]]:
    """Return the (topic, config) discovery messages of one device, in port and tag order."""
    mac = device["mac"]
    messages = []
    for port in device.get("ports", []):
        port_no = port["port"]
        label = port.get("label") or f"Port {port_no}"
        tags = port.get("tags") or DEFAULT_POWER_TAGS
        for tag in tags:
            component = "switch" if tag == "output" else "sensor"
            topic = f"{discovery_prefix}/{component}/mfi_{mac}/{port_no}_{tag}/config"
            config = {
                "unique_id": f"mfi_{mac}_{port_no}_{tag}",
                "name": f"{label} {QUANTITY_NAME.get(tag, tag)}",
                "state_topic": f"{topic_prefix}/{mac}/{port_no}/{tag}",
                "availability_topic": f"{topic_prefix}/{mac}/availability",
                "device": _device_block(device),
            }
            if tag == "output":
                config.update(
                    command_topic=f"{topic_prefix}/{mac}/{port_no}/output/set",
                    payload_on="ON",
                    payload_off="OFF",
                    state_on="ON",
                    state_off="OFF",
                )
            else:
                config.update(SENSOR_FIELDS.get(tag, {}))
            messages.append((topic, config))
    return messages


def _device_block(device: dict) -> dict:
    """Return a new device block: every entity of one device shares the same identifiers."""
    block = {
        "identifiers": [f"mfi_{device['mac']}"],
        "manufacturer": "Ubiquiti",
        "model": device.get("model", ""),
        "name": device.get("name") or f"mFi {device['mac']}",
    }
    if device.get("firmware"):
        block["sw_version"] = device["firmware"]
    return block
