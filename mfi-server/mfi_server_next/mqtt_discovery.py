"""Home Assistant MQTT discovery and state messages. Pure functions, standard library only.

Clean room, no I/O. The topic scheme is shared with mqtt.py (EPIC-14):
availability f"{topic_prefix}/{mac}/availability", state f"{topic_prefix}/{mac}/{port}/{tag}",
command f"{topic_prefix}/{mac}/{port}/output/set" and discovery
f"{discovery_prefix}/{component}/mfi_{mac}/{object_id}/config" (retained JSON).

An unknown sensor model is skipped, never raised. A device without any entity
(IWS1U, mPort Serial without sensors) gets no message at all, not even the alarm.
"""

from mfi_server_next.sensors import (
    DIMMER_MODELS,
    INWALL_OUTLETS,
    MPORT_MODELS,
    MPOWER_OUTLETS,
    OUTLET_TAGS,
    outlet_count,
)

OUTLET_MODELS = frozenset(MPOWER_OUTLETS) | frozenset(INWALL_OUTLETS)
BINARY_TAGS = frozenset({"motion", "tamper", "door", "input"})

# Measure sensor of every outlet: tag -> (name, config fields). The output tag is a switch.
OUTLET_MEASURES = {
    "active_pwr": ("Power", {"device_class": "power", "unit_of_measurement": "W", "state_class": "measurement"}),
    "pf": ("Power Factor", {"device_class": "power_factor", "state_class": "measurement"}),
    "energy_sum": ("Energy", {"device_class": "energy", "unit_of_measurement": "Wh", "state_class": "total_increasing"}),
    "v_rms": ("Voltage", {"device_class": "voltage", "unit_of_measurement": "V", "state_class": "measurement"}),
    "i_rms": ("Current", {"device_class": "current", "unit_of_measurement": "A", "state_class": "measurement"}),
}

_TEMPERATURE = {"device_class": "temperature", "unit_of_measurement": "\u00b0C", "state_class": "measurement"}
_MOTION_TAMPER = (
    ("motion", "binary_sensor", {"device_class": "motion"}, "Motion"),
    ("tamper", "binary_sensor", {"device_class": "tamper"}, "Tamper"),
)
_OUTPUT = (("output", "switch", {}, "Output"),)

# Sensor model -> entities as (tag, component, config fields, name). The tag is the
# last topic level; the object_id is f"{port}_{tag}".
MPORT_ENTITIES = {
    "MSW": _MOTION_TAMPER,
    "MSC": _MOTION_TAMPER,
    "DS": (("door", "binary_sensor", {"device_class": "door"}, "Door"),),
    "CS": (
        ("current", "sensor", {"device_class": "current", "unit_of_measurement": "A", "state_class": "measurement"}, "Current"),
        ("amp_hours", "sensor", {"unit_of_measurement": "Ah", "state_class": "total_increasing"}, "Amp Hours"),
    ),
    "THS": (
        ("temperature", "sensor", _TEMPERATURE, "Temperature"),
        ("humidity", "sensor", {"device_class": "humidity", "unit_of_measurement": "%", "state_class": "measurement"}, "Humidity"),
    ),
    "RTD": (("temperature", "sensor", _TEMPERATURE, "Temperature"),),
    "Counter": (("counter", "sensor", {"state_class": "total_increasing"}, "Counter"),),
    "Input Analog": (
        ("voltage", "sensor", {"device_class": "voltage", "unit_of_measurement": "V", "state_class": "measurement"}, "Voltage"),
    ),
    "Input Digital": (("input", "binary_sensor", {}, "Input"),),
    "Output 5v": _OUTPUT,
    "Output 12v": _OUTPUT,
    "Output 24v": _OUTPUT,
    "UVC PRO": _OUTPUT,
}


def _device_block(device):
    """A new device block; every entity of one device shares the same identifiers."""
    return {
        "identifiers": [f"mfi_{device['mac']}"],
        "manufacturer": "Ubiquiti",
        "model": device.get("model", ""),
        "name": device.get("name") or f"mFi {device['mac']}",
    }


def _command_topic(topic_prefix, mac, port):
    """The topic that carries ON and OFF commands of one output port."""
    return f"{topic_prefix}/{mac}/{port}/output/set"


def _switch_fields(command_topic):
    """Command topic, ON/OFF payloads and state values of a switch."""
    return {
        "command_topic": command_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "state_on": "ON",
        "state_off": "OFF",
    }


def _entity(device, component, object_id, state_topic, name, fields, discovery_prefix, topic_prefix):
    """Return (config_topic, config) of one entity; the config is a new dict."""
    mac = device["mac"]
    config = {
        "unique_id": f"mfi_{mac}_{object_id}",
        "name": name,
        "state_topic": state_topic,
        "availability_topic": f"{topic_prefix}/{mac}/availability",
        "device": _device_block(device),
        **fields,
    }
    return f"{discovery_prefix}/{component}/mfi_{mac}/{object_id}/config", config


def _outlet_entities(device, model, discovery_prefix, topic_prefix):
    """Switches (or one light per outlet of a dimmer), each switch with its measure sensors."""
    mac = device["mac"]
    entities = []
    for port in range(1, outlet_count(model) + 1):
        command = _command_topic(topic_prefix, mac, port)
        output = f"{topic_prefix}/{mac}/{port}/output"
        if model in DIMMER_MODELS:
            # Brightness is read only: the command topic carries ON and OFF. The 0-100 scale is INFERRED.
            fields = {
                "command_topic": command,
                "payload_on": "ON",
                "payload_off": "OFF",
                "brightness": True,
                "brightness_scale": 100,
                "brightness_state_topic": f"{topic_prefix}/{mac}/{port}/dimmer_level",
            }
            entities.append(
                _entity(device, "light", f"{port}_output", output, f"Outlet {port}", fields, discovery_prefix, topic_prefix)
            )
            continue
        entities.append(
            _entity(device, "switch", f"{port}_output", output, f"Outlet {port}", _switch_fields(command),
                    discovery_prefix, topic_prefix)
        )
        for tag in OUTLET_TAGS:
            if tag == "output":
                continue
            title, fields = OUTLET_MEASURES[tag]
            entities.append(
                _entity(device, "sensor", f"{port}_{tag}", f"{topic_prefix}/{mac}/{port}/{tag}",
                        f"Outlet {port} {title}", fields, discovery_prefix, topic_prefix)
            )
    return entities


def _sensor_entities(device, sensors, discovery_prefix, topic_prefix):
    """Entities of the sensors plugged into the ports of an mPort; invalid or unknown items are skipped."""
    mac = device["mac"]
    entities = []
    seen = set()
    for sensor in sensors or ():
        if not isinstance(sensor, dict):
            continue
        port = sensor.get("port")
        model = sensor.get("model")
        if isinstance(port, bool) or not isinstance(port, int) or not isinstance(model, str):
            continue
        if not 1 <= port <= 255:
            continue
        plan = MPORT_ENTITIES.get(model)
        if plan is None:
            continue
        if port in seen:
            continue
        seen.add(port)
        label = sensor.get("label") or f"Port {port}"
        for tag, component, fields, title in plan:
            extra = _switch_fields(_command_topic(topic_prefix, mac, port)) if component == "switch" else {}
            entities.append(
                _entity(device, component, f"{port}_{tag}", f"{topic_prefix}/{mac}/{port}/{tag}",
                        f"{label} {title}", {**extra, **fields}, discovery_prefix, topic_prefix)
            )
    return entities


def _alarm_entity(device, discovery_prefix, topic_prefix):
    """The problem sensor of a device. Its state topic is not published by state_messages (ports only)."""
    mac = device["mac"]
    return _entity(device, "binary_sensor", "alarm", f"{topic_prefix}/{mac}/alarm", "Alarm",
                   {"device_class": "problem"}, discovery_prefix, topic_prefix)


def discovery_messages(device, sensors=(), *, discovery_prefix="homeassistant", topic_prefix="mfi"):
    """Return the (config_topic, config) discovery messages of one device.

    device: {"mac", "model", "name"?, "firmware"?}. sensors: {"port", "model", "label"?} dicts,
    used only by the mPort models. A device without any entity gives [].
    """
    model = device.get("model")
    if not isinstance(model, str):
        return []
    if model in MPORT_MODELS:
        entities = _sensor_entities(device, sensors, discovery_prefix, topic_prefix)
    elif model in OUTLET_MODELS:
        entities = _outlet_entities(device, model, discovery_prefix, topic_prefix)
    else:
        return []
    if entities:
        entities.append(_alarm_entity(device, discovery_prefix, topic_prefix))
    return entities


def state_messages(device, values, *, topic_prefix="mfi"):
    """Return the (topic, payload) state messages of one device.

    values: {port: {tag: value}}. The output tag is b"ON" or b"OFF" by truthiness,
    every other tag is str(value) encoded as UTF-8.
    """
    mac = device["mac"]
    messages = []
    for port, tagmap in values.items():
        for tag, value in tagmap.items():
            if tag == "output" or tag in BINARY_TAGS:
                payload = b"ON" if value else b"OFF"
            elif value is None:
                continue
            else:
                payload = str(value).encode("utf-8")
            messages.append((f"{topic_prefix}/{mac}/{port}/{tag}", payload))
    return messages
