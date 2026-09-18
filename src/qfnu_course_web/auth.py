from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

import httpx

from .client import TeachingClient


class OcrRecognizer(Protocol):
    async def start(self) -> None: ...

    async def recognize(self, content: bytes) -> str: ...


class AuthError(RuntimeError):
    pass


class OcrError(AuthError):
    pass


class ManualCaptchaRequired(AuthError):
    def __init__(self, captcha_data_url: str, message: str = "需要手动输入验证码") -> None:
        super().__init__(message)
        self.captcha_data_url = captcha_data_url


@dataclass(frozen=True, slots=True)
class AuthResult:
    authenticated: bool
    username: str


@dataclass(frozen=True, slots=True)
class CaptchaChallenge:
    content: bytes
    media_type: str

    @property
    def data_url(self) -> str:
        encoded = base64.b64encode(self.content).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


def encode_credentials(username: str, password: str, scode: str, sxh: str) -> str:
    plain = f"{username}%%%{password}"
    result: list[str] = []
    cursor = 0
    for index, character in enumerate(plain):
        result.append(character)
        if index >= 20 or index >= len(sxh) or not sxh[index].isdigit():
            continue
        count = int(sxh[index])
        result.append(scode[cursor : cursor + count])
        cursor += count
    return "".join(result)


class AuthService:
    def __init__(
        self,
        client: TeachingClient,
        *,
        ocr_transport: httpx.AsyncBaseTransport | None = None,
        builtin_ocr: OcrRecognizer | None = None,
    ) -> None:
        self.client = client
        self._ocr_transport = ocr_transport
        self._builtin_ocr = builtin_ocr
        self._ocr_http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._builtin_ocr is not None:
            await self._builtin_ocr.start()

    async def close(self) -> None:
        if self._ocr_http is not None:
            await self._ocr_http.aclose()

    async def fetch_captcha(self) -> CaptchaChallenge:
        response = await self.client.request("GET", "/", check_session=False)
        if response.status_code >= 400:
            raise AuthError("无法初始化登录会话")
        captcha = await self.client.request("GET", "/verifycode.servlet", check_session=False)
        if captcha.status_code != 200 or not captcha.content:
            raise AuthError("无法获取验证码")
        media_type = captcha.headers.get("content-type", "image/jpeg").split(";", 1)[0]
        return CaptchaChallenge(content=captcha.content, media_type=media_type)

    async def begin_login(self) -> str:
        return (await self.fetch_captcha()).data_url

    async def recognize_captcha(self, ocr_url: str | None, content: bytes) -> str:
        if not ocr_url:
            if self._builtin_ocr is None:
                raise OcrError("内置 OCR 不可用")
            try:
                return await self._builtin_ocr.recognize(content)
            except Exception as exc:
                raise OcrError(f"内置 OCR 识别失败：{exc}") from exc
        if self._ocr_http is None:
            self._ocr_http = httpx.AsyncClient(
                transport=self._ocr_transport, timeout=httpx.Timeout(10, connect=5)
            )
        endpoint = ocr_url.rstrip("/")
        if not endpoint.endswith("/ocr"):
            endpoint = f"{endpoint}/ocr"
        response = await self._ocr_http.post(
            endpoint,
            data={"image": base64.b64encode(content).decode("ascii")},
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise OcrError("OCR 响应不是有效 JSON") from exc
        if str(payload.get("code")) != "200" or not str(payload.get("data", "")).strip():
            raise OcrError(str(payload.get("message") or "OCR 识别失败"))
        return str(payload["data"]).strip()

    async def automatic_login(
        self,
        username: str,
        password: str,
        ocr_url: str | None,
        *,
        attempts: int = 3,
    ) -> AuthResult:
        if not ocr_url and self._builtin_ocr is None:
            challenge = await self.fetch_captcha()
            raise ManualCaptchaRequired(challenge.data_url, "内置 OCR 不可用，需要手动验证码")
        last_error = "OCR 自动登录失败"
        for _ in range(attempts):
            challenge = await self.fetch_captcha()
            try:
                code = await self.recognize_captcha(ocr_url, challenge.content)
                return await self.complete_login(username, password, code)
            except (OcrError, httpx.HTTPError) as exc:
                last_error = str(exc)
            except AuthError as exc:
                if "验证码" not in str(exc):
                    raise
                last_error = str(exc)
        challenge = await self.fetch_captcha()
        raise ManualCaptchaRequired(challenge.data_url, f"{last_error}，请手动输入验证码")

    async def check_session(self) -> bool:
        response = await self.client.request(
            "GET", "/jsxsd/framework/xsMain.jsp", check_session=False
        )
        if response.status_code != 200 or response.is_redirect:
            return False
        return any(marker in response.text for marker in ("教学一体化服务平台", "glyphicon-class"))

    async def complete_login(self, username: str, password: str, captcha: str) -> AuthResult:
        seed = await self.client.request(
            "POST", "/Logon.do?method=logon&flag=sess", content=b"", check_session=False
        )
        parts = seed.text.strip().split("#")
        if len(parts) != 2 or not all(parts) or seed.text.strip() == "no":
            raise AuthError("登录会话参数无效，请刷新验证码")
        encoded = encode_credentials(username, password, parts[0], parts[1])
        response = await self.client.request(
            "POST",
            "/Logon.do?method=logonLdap",
            data={
                "userAccount": "",
                "userPassword": "",
                "RANDOMCODE": captcha,
                "encoded": encoded,
            },
            allow_login_redirects=True,
            check_session=False,
        )
        text = response.text
        if any(
            marker in text
            for marker in ("密码错误", "用户名或密码错误", "用户名密码错误", "用户名或者密码有误")
        ):
            raise AuthError("账号或密码错误")
        if "验证码" in text and any(marker in text for marker in ("错误", "不正确")):
            raise AuthError("验证码错误")
        verify = await self.client.request(
            "GET", "/jsxsd/framework/xsMain.jsp", check_session=False
        )
        if verify.status_code != 200 or not any(
            marker in verify.text for marker in ("教学一体化服务平台", "glyphicon-class")
        ):
            raise AuthError("登录状态验证失败")
        return AuthResult(authenticated=True, username=username)
