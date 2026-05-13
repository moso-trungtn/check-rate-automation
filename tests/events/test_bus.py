import asyncio

import pytest

from app.events.bus import Event, EventBus


@pytest.mark.asyncio
async def test_publish_received_by_subscriber() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def consume() -> None:
        async for ev in bus.subscribe("sess1"):
            received.append(ev)
            if ev.type == "done":
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    bus.publish("sess1", Event(type="progress", data={"step": "moso", "status": "started"}))
    bus.publish("sess1", Event(type="done", data={"report_id": "r1"}))
    await asyncio.wait_for(task, timeout=1)
    assert [e.type for e in received] == ["progress", "done"]


@pytest.mark.asyncio
async def test_publish_isolated_per_session() -> None:
    bus = EventBus()
    received_a: list[Event] = []
    received_b: list[Event] = []

    async def consume(sess: str, sink: list[Event]) -> None:
        async for ev in bus.subscribe(sess):
            sink.append(ev)
            if ev.type == "done":
                break

    ta = asyncio.create_task(consume("a", received_a))
    tb = asyncio.create_task(consume("b", received_b))
    await asyncio.sleep(0.01)
    bus.publish("a", Event(type="progress", data={"step": "x"}))
    bus.publish("b", Event(type="error", data={"msg": "y"}))
    bus.publish("a", Event(type="done", data={}))
    bus.publish("b", Event(type="done", data={}))
    await asyncio.gather(ta, tb)
    assert [e.type for e in received_a] == ["progress", "done"]
    assert [e.type for e in received_b] == ["error", "done"]
