"""Firmware file to serve for each device model.

Clean room, standard library only. The firmware file is not stored in this
repository: only its URL path is built here.
"""

FIRMWARE_VERSION = "2.1.11.1309"
FIRMWARE_PATH = "M2M/2.1.11.1309/firmware.bin"
FIRMWARE_MODELS = frozenset({"IWD1U", "P1E", "IWO2U", "P8U", "M2S", "M2M", "P6E", "P1U", "P3E", "P3U"})

# UNVERIFIED (needs device test R-UPDATE): the comparison rule (an upgrade is offered
# when the reported version differs from FIRMWARE_VERSION) and the format of the
# "version" field of the upgrade message come from docs/PROTOCOL.md and are not
# confirmed on a device.


def firmware_for_model(model=None):
    """Return the firmware version for a device model, or None when the model has no firmware."""
    if isinstance(model, str) and model in FIRMWARE_MODELS:
        return FIRMWARE_VERSION
    return None


def build_upgrade(model=None, host="mfi-server", port=6080):
    """Return the upgrade message for a device model, or None when the model has no firmware."""
    if firmware_for_model(model) is None:
        return None
    return {
        "_type": "upgrade",
        "url": f"http://{host}:{port}/dl/firmware/{FIRMWARE_PATH}",
        "version": FIRMWARE_VERSION,
    }
