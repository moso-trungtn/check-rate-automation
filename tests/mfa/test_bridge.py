import asyncio

import pytest

from app.mfa.bridge import MfaAlreadySubmitted, MfaBridge, MfaTimeout, MfaUnknownSession


@pytest.mark.asyncio
async def test_request_then_submit_resolves() -> None:
    bridge = MfaBridge()

    async def submit_later() -> None:
        await asyncio.sleep(0.05)
        bridge.submit_code("sess1", "123456")

    task = asyncio.create_task(submit_later())
    code = await bridge.request_code("sess1", "Test Lender", timeout=1.0)
    await task
    assert code == "123456"


@pytest.mark.asyncio
async def test_request_times_out() -> None:
    bridge = MfaBridge()
    with pytest.raises(MfaTimeout):
        await bridge.request_code("sess2", "Test Lender", timeout=0.1)


@pytest.mark.asyncio
async def test_double_submit_rejected() -> None:
    bridge = MfaBridge()

    async def consumer() -> str:
        return await bridge.request_code("sess3", "L", timeout=1.0)

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)
    bridge.submit_code("sess3", "111111")
    with pytest.raises(MfaAlreadySubmitted):
        bridge.submit_code("sess3", "222222")
    assert await task == "111111"


def test_submit_unknown_session_raises() -> None:
    bridge = MfaBridge()
    with pytest.raises(MfaUnknownSession):
        bridge.submit_code("nope", "x")
