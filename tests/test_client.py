import asyncio

import httpx
import pytest

from qfnu_course_web.client import (
    RemoteLoginError,
    SessionExpiredError,
    TeachingClient,
    UnsafeRedirectError,
)
from qfnu_course_web.rate_limit import GlobalRateLimiter


@pytest.mark.asyncio
async def test_limiter_spaces_requests() -> None:
    now = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    limiter = GlobalRateLimiter(2, clock=clock, sleep=sleep)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    assert sleeps == [0.5, 0.5]


@pytest.mark.asyncio
async def test_limiter_serializes_concurrent_requests_at_five_per_second() -> None:
    now = 0.0
    starts: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    limiter = GlobalRateLimiter(5, clock=clock, sleep=sleep)

    async def acquire() -> None:
        await limiter.acquire()
        starts.append(now)

    await asyncio.gather(*(acquire() for _ in range(4)))

    assert starts == pytest.approx([0, 0.2, 0.4, 0.6])


@pytest.mark.asyncio
async def test_client_rejects_cross_origin_redirect() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "https://evil.example/x"})
    )
    client = TeachingClient(transport=transport)
    with pytest.raises(UnsafeRedirectError):
        await client.request("GET", "/", allow_login_redirects=True)
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("请输入账号 请输入密码 请输入验证码", SessionExpiredError),
        ("您的账号在其它地方登录", RemoteLoginError),
    ],
)
async def test_client_classifies_session_pages(body: str, error: type[Exception]) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    client = TeachingClient(transport=transport)
    with pytest.raises(error):
        await client.request("GET", "/jsxsd/xsxk/xklc_list")
    await client.close()
