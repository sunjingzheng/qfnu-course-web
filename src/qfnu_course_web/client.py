from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx

from .rate_limit import GlobalRateLimiter

BASE_URL = "http://zhjw.qfnu.edu.cn"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


class TeachingClientError(RuntimeError):
    pass


class UnsafeRedirectError(TeachingClientError):
    pass


class SessionExpiredError(TeachingClientError):
    pass


class RemoteLoginError(TeachingClientError):
    pass


class RateLimitedError(TeachingClientError):
    def __init__(self, retry_after: float | None) -> None:
        super().__init__("服务端要求降低请求频率")
        self.retry_after = retry_after


EventCallback = Callable[[str, str, int, float], Awaitable[None] | None]


class TeachingClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        requests_per_second: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: GlobalRateLimiter | None = None,
        on_request: EventCallback | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = self._origin(self.base_url)
        self.limiter = limiter or GlobalRateLimiter(requests_per_second)
        self.on_request = on_request
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(15, connect=10),
        )

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlparse(url)
        return parsed.scheme, parsed.hostname or "", parsed.port

    async def close(self) -> None:
        await self.http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        allow_login_redirects: bool = False,
        check_session: bool = True,
        max_redirects: int = 5,
        **kwargs: object,
    ) -> httpx.Response:
        current = path
        for _ in range(max_redirects + 1):
            await self.limiter.acquire()
            started = time.monotonic()
            response = await self.http.request(method, current, **kwargs)
            duration = time.monotonic() - started
            if self.on_request:
                result = self.on_request(
                    method, urlparse(str(response.request.url)).path, response.status_code, duration
                )
                if result is not None:
                    await result
            if response.status_code == 429:
                retry = response.headers.get("retry-after")
                raise RateLimitedError(
                    float(retry) if retry and retry.replace(".", "", 1).isdigit() else None
                )
            if response.is_redirect:
                location = response.headers.get("location", "")
                target = urljoin(str(response.request.url), location)
                if not allow_login_redirects or self._origin(target) != self.origin:
                    if allow_login_redirects:
                        raise UnsafeRedirectError("拒绝跨源登录重定向")
                    return response
                current = target
                method = "GET"
                kwargs = {}
                continue
            if check_session:
                text = response.text
                if "您的账号在其它地方登录" in text:
                    raise RemoteLoginError("账号在其他位置登录")
                login_markers = ("请输入账号", "请输入密码", "请输入验证码")
                if all(marker in text for marker in login_markers):
                    raise SessionExpiredError("登录会话已失效")
            return response
        raise TeachingClientError("登录重定向次数过多")
