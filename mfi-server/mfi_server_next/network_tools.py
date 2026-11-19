"""Network tools: web shell to an adopted mPort Serial, SSH from the browser,
UPnP announcements and the guest access page, all off by default. Implemented
in EPIC-13. ASSUMPTION (EPIC-00): not named in the REBUILD-PLAN module table.
"""


def open_webshell(host=None, port=None, protocol=None):
    """Open a web shell to an adopted mPort Serial. Implemented in EPIC-13."""
    raise NotImplementedError("network_tools: implemented in EPIC-13")


def start_browser_ssh(host=None, port=None):
    """Start an SSH session from the browser. Implemented in EPIC-13."""
    raise NotImplementedError("network_tools: implemented in EPIC-13")


def upnp_announce():
    """Send the UPnP announcements. Implemented in EPIC-13."""
    raise NotImplementedError("network_tools: implemented in EPIC-13")


def guest_portal():
    """Serve the guest access page. Implemented in EPIC-13."""
    raise NotImplementedError("network_tools: implemented in EPIC-13")
