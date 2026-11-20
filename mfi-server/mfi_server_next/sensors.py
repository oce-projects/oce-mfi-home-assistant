"""Sensor port layout and the registry of mFi sensor ports.

Standard library only, clean room. Facts that are not verified on a device
(power of P1U, P3U and P8U, output port number of an mPort, dimmer scale,
behaviour of IWS1U) are comments only and are not used by the code.
"""

import re

# Outlets of the mPower family, by model. UNVERIFIED: the power of P1U, P3U and
# P8U (the controller treats them like the E models, docs/controller/mpower.md).
MPOWER_OUTLETS = {"P1U": 1, "P1E": 1, "P3U": 3, "P3E": 3, "P8U": 8, "P6E": 6}

# In-wall devices with outputs. IWS1U is left out on purpose: it has no official
# product and its behaviour is UNVERIFIED, so it has 0 ports and no entity.
INWALL_OUTLETS = {"IWO2U": 2, "IWD1U": 1}

# mPort devices: ports created at adoption. UNVERIFIED: the output port number
# of an mPort is not known, so no output is derived from it here.
MPORT_PORTS = {"M2M": 3, "M2S": 1}

# The dimmer scale is UNVERIFIED on a device, so no level scale is coded.
DIMMER_MODELS = frozenset({"IWD1U"})
DEFAULT_DIMMER_MODE = "switch"

# Models configured with vpower lines, and models configured with port.N lines.
VPOWER_MODELS = frozenset(MPOWER_OUTLETS) | {"IWO2U", "IWD1U", "IWS1U"}
MPORT_MODELS = frozenset(MPORT_PORTS)

OUTLET_TAGS = ("output", "pf", "energy_sum", "v_rms", "i_rms", "active_pwr")

# A device MAC as the controller writes it: 12 lowercase hex digits, no colons.
MAC_PATTERN = re.compile(r"[0-9a-f]{12}")


def outlet_count(model):
    """Number of switchable outputs of a model. An unknown model raises ValueError."""
    if not isinstance(model, str):
        raise ValueError("model")
    if model in VPOWER_MODELS:
        return MPOWER_OUTLETS.get(model, INWALL_OUTLETS.get(model, 0))
    if model in MPORT_MODELS:
        # mPort outputs depend on the sensors assigned to the ports.
        return 0
    raise ValueError("model")


def port_count(model):
    """Number of ports created at adoption. An unknown model raises ValueError."""
    if isinstance(model, str) and model in MPORT_MODELS:
        return MPORT_PORTS[model]
    return outlet_count(model)


def device_cfg(model):
    """Device configuration sent with the model. Only the dimmer has one."""
    if isinstance(model, str) and model in DIMMER_MODELS:
        return {"dimmer_mode": DEFAULT_DIMMER_MODE}
    return {}


def parse_measurements(alarm=None):
    """Flatten the inform alarm list into one reading per value.

    An item with entries gives one reading per entry: the parent fields (without
    entries) merged with the entry, the entry winning. An item without entries
    is copied without an entries key. None or a non-list gives [].
    """
    if not isinstance(alarm, list):
        return []
    readings = []
    for item in alarm:
        if not isinstance(item, dict):
            continue
        parent = {key: value for key, value in item.items() if key != "entries"}
        entries = item.get("entries")
        if not isinstance(entries, list):
            readings.append(parent)
            continue
        for entry in entries:
            if isinstance(entry, dict):
                readings.append({**parent, **entry})
    return readings


def _assigned_sensors(request):
    """The sensor dicts of a request: the `sensor` field, the `sensors` list, or both."""
    found = []
    if request.get("sensor") is not None:
        found.append(request["sensor"])
    if request.get("sensors") is not None:
        sensors = request["sensors"]
        if not isinstance(sensors, list):
            raise ValueError("sensors")
        found.extend(sensors)
    for sensor in found:
        if not isinstance(sensor, dict):
            raise ValueError("sensor")
    return found


def _reject_line_break(value, field):
    """Reject a value with a line break: it could inject a config line into the device."""
    if "\n" in value or "\r" in value:
        raise ValueError(field)


def _mport_port_lines(model, request):
    """port.N lines of an mPort: one block per port, empty ports marked off."""
    count = MPORT_PORTS[model]
    assigned = {}
    for sensor in _assigned_sensors(request):
        port = sensor.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= count:
            raise ValueError("port")
        sensor_model = sensor.get("model")
        label = sensor.get("label", "")
        if not isinstance(sensor_model, str) or not isinstance(label, str):
            raise ValueError("sensor")
        _reject_line_break(sensor_model, "sensor")
        _reject_line_break(label, "label")
        assigned[port] = (sensor_model, label)
    lines = []
    for port in range(1, count + 1):
        if port not in assigned:
            lines.append(f"port.{port}.mode=off")
            continue
        sensor_model, label = assigned[port]
        lines.append(f"port.{port}.model={sensor_model}")
        lines.append(f"port.{port}.label={label}")
        lines.append(f"port.{port}.sensorId={port}")
    return "\n".join(lines)


def _vpower_lines(model):
    """vpower lines of an outlet device: output and lock of every outlet, none for IWS1U."""
    lines = []
    for index in range(1, outlet_count(model) + 1):
        lines.append(f"vpower.{index}.output=0")
        lines.append(f"vpower.{index}.lock=0")
    return "\n".join(lines)


def build_port_config(request=None):
    """Build the setparam message that sets the ports of a device.

    Without a usable request (None, not a dict, no model) the message has an
    empty port_cfg and nothing is raised. An unknown model, or a sensor on a
    port outside the device range, raises ValueError.
    """
    message = {"_type": "setparam", "mgmt": {"port_cfg": ""}}
    if not isinstance(request, dict) or "model" not in request:
        return message
    model = request["model"]
    if isinstance(model, str) and model in MPORT_MODELS:
        message["mgmt"]["port_cfg"] = _mport_port_lines(model, request)
        return message
    message["mgmt"]["port_cfg"] = _vpower_lines(model)
    cfg = device_cfg(model)
    if cfg:
        message["mgmt"]["device_cfg"] = "\n".join(f"{key}={value}" for key, value in cfg.items())
    return message


def _check_placement(mac, port):
    """Reject a mac that is not 12 lowercase hex digits or a port that is not a positive integer."""
    if not isinstance(mac, str) or not MAC_PATTERN.fullmatch(mac):
        raise ValueError("mac")
    if isinstance(port, bool) or not isinstance(port, int) or port < 1:
        raise ValueError("port")


class SensorRegistry:
    """Sensors known to the server, keyed by sId. A (mac, port) holds at most one sensor."""

    def __init__(self):
        self._sensors = {}
        self._next_id = 1

    def _unlink(self, mac, port, keep=None):
        """Remove the sensor on (mac, port), except the sensor with sId `keep`."""
        for s_id, sensor in list(self._sensors.items()):
            if s_id != keep and sensor["mac"] == mac and sensor["port"] == port:
                del self._sensors[s_id]

    def add(self, mac, port, model, label=""):
        """Create a sensor on (mac, port). A sensor already there is unlinked."""
        _check_placement(mac, port)
        if not isinstance(model, str):
            raise ValueError("model")
        _reject_line_break(model, "model")
        if not isinstance(label, str):
            raise ValueError("label")
        _reject_line_break(label, "label")
        self._unlink(mac, port)
        s_id = self._next_id
        self._next_id += 1
        sensor = {
            "sId": s_id,
            "mac": mac,
            "port": port,
            "model": model,
            "label": label,
            "calibration": "xyz",
            "output_val": 0,
            "configed_val": None,
            "output_lock": 0,
        }
        self._sensors[s_id] = sensor
        return dict(sensor)

    def move(self, s_id, new_mac, new_port):
        """Move a sensor to another mac and port, keeping its sId, label and calibration."""
        sensor = self._sensors.get(s_id)
        if sensor is None:
            raise ValueError("sId")
        _check_placement(new_mac, new_port)
        self._unlink(new_mac, new_port, keep=s_id)
        sensor["mac"] = new_mac
        sensor["port"] = new_port
        return dict(sensor)

    def remove(self, s_id):
        """Forget a sensor. An unknown sId is ignored."""
        self._sensors.pop(s_id, None)

    def get(self, s_id):
        """A copy of the sensor, or None when the sId is unknown."""
        sensor = self._sensors.get(s_id)
        return None if sensor is None else dict(sensor)

    def list(self):
        """Copies of every sensor, in creation order."""
        return [dict(sensor) for sensor in self._sensors.values()]

    def set_calibration(self, s_id, calibration="xyz"):
        """Set the calibration string of a sensor. An unknown sId raises ValueError."""
        sensor = self._sensors.get(s_id)
        if sensor is None:
            raise ValueError("sId")
        if not isinstance(calibration, str):
            raise ValueError("calibration")
        _reject_line_break(calibration, "calibration")
        sensor["calibration"] = calibration
        return dict(sensor)
