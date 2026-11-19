"""Device archive: devices.json, atomic writes and transactions. Implemented in EPIC-01."""


class Store:
    """Device archive stored in devices.json. Implemented in EPIC-01."""

    def __init__(self):
        raise NotImplementedError("store: implemented in EPIC-01")

    def open(self):
        """Open devices.json in the data folder. Implemented in EPIC-01."""
        raise NotImplementedError("store: implemented in EPIC-01")

    def transaction(self):
        """Run a group of writes that succeed or fail together. Implemented in EPIC-01."""
        raise NotImplementedError("store: implemented in EPIC-01")
