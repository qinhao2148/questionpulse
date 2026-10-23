import asyncio

import pytest

from app.core.session_gate import _gates, session_cluster_gate


def test_gate_serializes_submissions_for_one_classroom() -> None:
    events: list[str] = []

    async def worker(name: str) -> None:
        async with session_cluster_gate("room-1"):
            events.append(f"{name}-enter")
            await asyncio.sleep(0.05)
            events.append(f"{name}-exit")

    async def main() -> None:
        await asyncio.gather(worker("a"), worker("b"))

    asyncio.run(main())

    assert events == ["a-enter", "a-exit", "b-enter", "b-exit"]


def test_gate_does_not_block_other_classrooms() -> None:
    order: list[str] = []

    async def slow() -> None:
        async with session_cluster_gate("room-a"):
            order.append("slow-enter")
            await asyncio.sleep(0.2)
            order.append("slow-exit")

    async def fast() -> None:
        await asyncio.sleep(0.02)
        async with session_cluster_gate("room-b"):
            order.append("fast")

    async def main() -> None:
        await asyncio.gather(slow(), fast())

    asyncio.run(main())

    assert order == ["slow-enter", "fast", "slow-exit"]


def test_gate_releases_after_exception() -> None:
    async def main() -> None:
        with pytest.raises(RuntimeError):
            async with session_cluster_gate("room-x"):
                raise RuntimeError("boom")
        async with session_cluster_gate("room-x"):
            return
    asyncio.run(main())


def test_gate_forgets_idle_classrooms() -> None:
    async def main() -> None:
        async with session_cluster_gate("room-cleanup"):
            pass

    asyncio.run(main())

    assert "room-cleanup" not in _gates
