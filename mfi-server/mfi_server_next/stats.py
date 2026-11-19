"""Statistics: aggregates measured values over time intervals. Implemented in EPIC-07."""


class Aggregator:
    """Collects values and reads their aggregates per interval. Implemented in EPIC-07."""

    def __init__(self):
        raise NotImplementedError("stats: implemented in EPIC-07")

    def add(self, value=None):
        """Add one measured value. Implemented in EPIC-07."""
        raise NotImplementedError("stats: implemented in EPIC-07")

    def read(self, interval=None):
        """Return the aggregate of one interval. Implemented in EPIC-07."""
        raise NotImplementedError("stats: implemented in EPIC-07")
