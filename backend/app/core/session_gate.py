"""Per-classroom serialization for question clustering.

Clustering is a read-modify-write section: read the clusters that exist, ask the
model whether the new question belongs to one of them, then either join or
create. When two submissions for the same classroom overlap, both read an empty
list -- the first request has not committed yet -- and each creates a cluster,
so two identical questions end up in two clusters that no longer merge.

Two things are needed to fix that:

1. Mutual exclusion, so the second request cannot run its read step while the
   first is still deciding.
2. A fresh snapshot once it gets in. MySQL defaults to REPEATABLE READ, so a
   session that already ran the authentication queries keeps reading the
   snapshot it opened before waiting, even after the other transaction commits.
   The gate therefore commits the caller's read-only transaction before the
   section runs, which makes the next query open a new snapshot.

The gate lives in process memory. The backend runs as a single uvicorn worker
(see scripts/start-demo.ps1), so this is sufficient. A multi-worker deployment
would need a database-backed lock such as SELECT ... FOR UPDATE on the session
row instead.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class _Gate:
    __slots__ = ("lock", "waiters")

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.waiters = 0


_gates: dict[str, _Gate] = {}


@asynccontextmanager
async def session_cluster_gate(session_id: str) -> AsyncIterator[None]:
    """Serialize the clustering section for one classroom.

    Only the read/decide/write part belongs inside. Network calls that are not
    needed for the decision, such as fetching POLYV records, should stay outside
    so they do not hold the gate for other submissions.
    """
    gate = _gates.get(session_id)
    if gate is None:
        gate = _Gate()
        _gates[session_id] = gate
    gate.waiters += 1
    try:
        async with gate.lock:
            yield
    finally:
        gate.waiters -= 1
        if gate.waiters == 0:
            _gates.pop(session_id, None)
