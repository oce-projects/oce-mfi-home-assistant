"""Serial port configuration of mPort Serial devices and the serial line reset.

Standard library only, clean room. Only the M2S receives ser2net_cfg
(docs/controller/mport-serial.md, section 1).
"""
import re

BAUD_RATES = (300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)
PARITIES = ("none", "odd", "even")
# RS422 is UNVERIFIED: the two official guides disagree (QSG-MPORT-S p. 7 lists
# it, UG-V11 p. 28 does not). It is rejected until a device confirms it.
UART_MODES = ("rs232", "rs485")
DEFAULT_SERIAL = {
    "enable": "off",
    "baudRate": 9600,
    "parity": "none",
    "uartMode": "rs232",
    "termination": "off",
    "antenna": "off",
}
SER2NET_KEYS = ("enable", "baudRate", "parity", "uartMode", "termination", "antenna")
# A device MAC as the controller writes it: 12 lowercase hex digits, no colons.
MAC_PATTERN = re.compile(r"[0-9a-f]{12}")


def _baud_rate(value):
    """The baud rate as an int: an int or a numeric string, and listed in BAUD_RATES."""
    try:
        baud = int(str(value))
    except ValueError:
        raise ValueError("baudRate") from None
    if baud not in BAUD_RATES:
        raise ValueError("baudRate")
    return baud


def _settings(request):
    """The serial settings of a request. Missing keys come from DEFAULT_SERIAL."""
    if request is None:
        return dict(DEFAULT_SERIAL)
    if not isinstance(request, dict):
        raise ValueError("serial")
    serial = request.get("serial")
    if serial is None:
        return dict(DEFAULT_SERIAL)
    if not isinstance(serial, dict):
        raise ValueError("serial")
    return {**DEFAULT_SERIAL, **serial}


def build_ser2net_cfg(request=None):
    """Build the setparam message that sets the ser2net configuration of an M2S.

    Without a request the default settings are used and nothing is raised. A
    baud rate outside BAUD_RATES, an unknown parity or UART mode raises
    ValueError naming the field.
    """
    settings = _settings(request)
    settings["baudRate"] = _baud_rate(settings["baudRate"])
    if settings["parity"] not in PARITIES:
        raise ValueError("parity")
    if settings["uartMode"] not in UART_MODES:
        raise ValueError("uartMode")
    lines = []
    for key in SER2NET_KEYS:
        value = str(settings[key])
        # a line break would start a new key in the device configuration
        if "\n" in value or "\r" in value:
            raise ValueError(key)
        lines.append(f"{key}={value}")
    return {"_type": "setparam", "mgmt": {"ser2net_cfg": "\n".join(lines)}}


def kick_serial(mac=None):
    """Build the command that resets the serial line of a device.

    A mac of None is allowed. A mac that is not 12 lowercase hex digits raises
    ValueError("mac").
    """
    if mac is not None and not (isinstance(mac, str) and MAC_PATTERN.fullmatch(mac)):
        raise ValueError("mac")
    return {"_type": "cmd", "cmd": "kick-serial", "mac": mac}
