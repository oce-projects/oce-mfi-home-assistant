"""Queue of commands waiting for the next inform of each device. Implemented in EPIC-02."""


class TaskQueue:
    """Commands queued for the devices, delivered on their next inform. Implemented in EPIC-02."""

    def __init__(self):
        raise NotImplementedError("tasks: implemented in EPIC-02")

    def enqueue(self, task=None):
        """Add one command to the queue. Implemented in EPIC-02."""
        raise NotImplementedError("tasks: implemented in EPIC-02")

    def pop_for_mac(self, mac=None):
        """Take the next queued command of one device. Implemented in EPIC-02."""
        raise NotImplementedError("tasks: implemented in EPIC-02")
