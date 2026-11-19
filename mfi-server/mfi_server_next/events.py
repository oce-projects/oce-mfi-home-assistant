"""Event log: records the device and server events. Implemented in EPIC-06."""


class EventLog:
    """Keeps the recorded events in order. Implemented in EPIC-06."""

    def __init__(self):
        raise NotImplementedError("events: implemented in EPIC-06")

    def record(self, event=None):
        """Record one event. Implemented in EPIC-06."""
        raise NotImplementedError("events: implemented in EPIC-06")
