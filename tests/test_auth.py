import base64

import httpx
import pytest

from qfnu_course_web.auth import (
    AuthError,
    AuthService,
    ManualCaptchaRequired,
    encode_credentials,
)
from qfnu_course_web.client import TeachingClient


def test_encode_credentials_matches_documented_example() -> None:
    # The prose algorithm preserves all three '%' characters; the document's
    # sample output accidentally omits the character at index 2.
    assert encode_credentials("u", "p", "ABC123", "201") == "uAB%%C%p"


@pytest.mark.asyncio
async def test_login_flow_uses_empty_plaintext_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text="home")
        if path == "/verifycode.servlet":
            return httpx.Response(200, content=b"jpeg")
        if path == "/Logon.do" and request.url.params.get("flag") == "sess":
            return httpx.Response(200, text="ABC123#201")
        if path == "/Logon.do":
            form = dict(httpx.QueryParams(request.content.decode()))
            assert form["userAccount"] == ""
            assert form["userPassword"] == ""
            assert form["RANDOMCODE"] == "abcd"
            assert form["encoded"] == "uAB%%C%p"
            return httpx.Response(302, headers={"location": "/handoff"})
        if path == "/handoff":
            return httpx.Response(302, headers={"location": "/jsxsd/framework/xsMain.jsp"})
        return httpx.Response(200, text="教学一体化服务平台")

    client = TeachingClient(transport=httpx.MockTransport(handler), requests_per_second=2)
    auth = AuthService(client)
    image = await auth.begin_login()
    assert base64.b64decode(image.split(",", 1)[1]) == b"jpeg"
    result = await auth.complete_login("u", "p", "abcd")
    assert result.authenticated is True
    await client.close()


@pytest.mark.asyncio
async def test_password_error_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Logon.do" and request.url.params.get("flag") == "sess":
            return httpx.Response(200, text="A#1")
        return httpx.Response(200, text="用户名或密码错误")

    client = TeachingClient(transport=httpx.MockTransport(handler))
    with pytest.raises(AuthError, match="账号或密码错误"):
        await AuthService(client).complete_login("u", "p", "x")
    await client.close()


@pytest.mark.asyncio
async def test_automatic_login_retries_a_bad_ocr_code() -> None:
    submitted_codes: list[str] = []
    ocr_codes = iter(["wrong", "abcd"])

    def teaching_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text="home")
        if path == "/verifycode.servlet":
            return httpx.Response(200, content=b"jpeg", headers={"content-type": "image/jpeg"})
        if path == "/Logon.do" and request.url.params.get("flag") == "sess":
            return httpx.Response(200, text="A#1")
        if path == "/Logon.do":
            code = dict(httpx.QueryParams(request.content.decode()))["RANDOMCODE"]
            submitted_codes.append(code)
            if code == "wrong":
                return httpx.Response(200, text="验证码错误")
            return httpx.Response(200, text="ok")
        return httpx.Response(200, text="教学一体化服务平台")

    def ocr_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ocr"
        assert (
            base64.b64decode(dict(httpx.QueryParams(request.content.decode()))["image"]) == b"jpeg"
        )
        return httpx.Response(200, json={"code": 200, "data": next(ocr_codes)})

    client = TeachingClient(transport=httpx.MockTransport(teaching_handler))
    auth = AuthService(client, ocr_transport=httpx.MockTransport(ocr_handler))

    result = await auth.automatic_login("u", "p", "http://ocr.local", attempts=2)

    assert result.authenticated is True
    assert submitted_codes == ["wrong", "abcd"]
    await auth.close()
    await client.close()


@pytest.mark.asyncio
async def test_automatic_login_uses_builtin_ocr_when_url_is_missing() -> None:
    submitted_codes: list[str] = []

    class FakeBuiltinOcr:
        async def start(self) -> None:
            return None

        async def recognize(self, content: bytes) -> str:
            assert content == b"jpeg"
            return "abcd"

    def teaching_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text="home")
        if path == "/verifycode.servlet":
            return httpx.Response(200, content=b"jpeg", headers={"content-type": "image/jpeg"})
        if path == "/Logon.do" and request.url.params.get("flag") == "sess":
            return httpx.Response(200, text="A#1")
        if path == "/Logon.do":
            submitted_codes.append(dict(httpx.QueryParams(request.content.decode()))["RANDOMCODE"])
            return httpx.Response(200, text="ok")
        return httpx.Response(200, text="教学一体化服务平台")

    client = TeachingClient(transport=httpx.MockTransport(teaching_handler))
    auth = AuthService(client, builtin_ocr=FakeBuiltinOcr())

    result = await auth.automatic_login("u", "p", None, attempts=1)

    assert result.authenticated is True
    assert submitted_codes == ["abcd"]
    await auth.close()
    await client.close()


@pytest.mark.asyncio
async def test_automatic_login_falls_back_to_a_manual_captcha() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text="home")
        return httpx.Response(200, content=b"captcha", headers={"content-type": "image/png"})

    client = TeachingClient(transport=httpx.MockTransport(handler))
    auth = AuthService(client)

    with pytest.raises(ManualCaptchaRequired) as captured:
        await auth.automatic_login("u", "p", None, attempts=3)

    assert captured.value.captcha_data_url.startswith("data:image/png;base64,")
    await auth.close()
    await client.close()


@pytest.mark.asyncio
async def test_check_session_recognizes_the_student_home_page() -> None:
    responses = iter(["教学一体化服务平台", "请输入账号 请输入密码 请输入验证码"])
    client = TeachingClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=next(responses)))
    )
    auth = AuthService(client)

    assert await auth.check_session() is True
    assert await auth.check_session() is False
    await auth.close()
    await client.close()
