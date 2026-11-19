"""Automation rules: the engine that runs automations and their store. Implemented in EPIC-05."""


class AutomationEngine:
    """Runs the automations and checks their triggers. Implemented in EPIC-05."""

    def __init__(self):
        raise NotImplementedError("rules: implemented in EPIC-05")

    def tick(self):
        """Advance the automations by one tick. Implemented in EPIC-05."""
        raise NotImplementedError("rules: implemented in EPIC-05")


class AutomationStore:
    """Keeps the automation definitions on disk. Implemented in EPIC-05."""

    def __init__(self):
        raise NotImplementedError("rules: implemented in EPIC-05")
