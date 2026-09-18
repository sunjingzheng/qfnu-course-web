import pytest

from qfnu_course_web.ocr import BuiltinOcr, BuiltinOcrError


@pytest.mark.asyncio
async def test_builtin_ocr_initializes_once_and_recognizes_in_a_worker() -> None:
    engines = []

    class FakeEngine:
        def classification(self, content: bytes) -> str:
            assert content == b"captcha"
            return " aB12\n"

    def factory():
        engine = FakeEngine()
        engines.append(engine)
        return engine

    ocr = BuiltinOcr(factory=factory)
    await ocr.start()
    await ocr.start()

    assert await ocr.recognize(b"captcha") == "aB12"
    assert len(engines) == 1


@pytest.mark.asyncio
async def test_builtin_ocr_rejects_an_empty_result() -> None:
    class FakeEngine:
        def classification(self, content: bytes) -> str:
            return ""

    ocr = BuiltinOcr(factory=FakeEngine)

    with pytest.raises(BuiltinOcrError, match="没有识别出验证码"):
        await ocr.recognize(b"captcha")
