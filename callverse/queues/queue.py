"""Queue of tickets waiting for an agent: high before medium before low, then first come, first served.

A heap keeps the tickets sorted by (priority rank, arrival number). The arrival number breaks ties,
so two tickets with the same label leave in the order they came in.
"""

import heapq
import itertools

from callverse import trace

RANK = {"high": 0, "medium": 1, "low": 2}


class QueueManager:
    def __init__(self):
        self._heap = []
        self._arrival = itertools.count()

    def __len__(self) -> int:
        return len(self._heap)

    def add(self, ticket: dict) -> None:
        """Put a ticket in the queue (traced as queue_add)."""
        n = next(self._arrival)
        heapq.heappush(self._heap, (RANK[ticket["priority_label"]], n, ticket))
        trace.log("queue_add", "queue", {"ticket_id": ticket.get("ticket_id"),
                                         "priority_label": ticket["priority_label"], "arrival": n,
                                         "size": len(self._heap)})

    def next(self) -> dict | None:
        """Take the most urgent ticket out of the queue (traced as queue_next); None when empty."""
        if not self._heap:
            return None
        _, n, ticket = heapq.heappop(self._heap)
        trace.log("queue_next", "queue", {"ticket_id": ticket.get("ticket_id"),
                                          "priority_label": ticket["priority_label"], "arrival": n,
                                          "left": len(self._heap)})
        return ticket
