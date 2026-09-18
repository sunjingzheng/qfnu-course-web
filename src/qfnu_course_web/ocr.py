from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol


class OcrEngine(Protocol):
    def classification(self, content: bytes) -> str: ...


class BuiltinOcrError(RuntimeError):
    pass


def create_default_engine() -> OcrEngine:
    import ddddocr

    return ddddocr.DdddOcr(show_ad=False)


class BuiltinOcr:
    def __init__(self, factory: Callable[[], OcrEngine] = create_default_engine) -> None:
        self._factory = factory
        self._engine: OcrEngine | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._engine is not None:
            return
        async with self._start_lock:
            if self._engine is None:
                self._engine = await asyncio.to_thread(self._factory)

    async def recognize(self, content: bytes) -> str:
        await self.start()
        if self._engine is None:  # pragma: no cover - guarded by start()
            raise BuiltinOcrError("内置 OCR 尚未初始化")
        result = str(await asyncio.to_thread(self._engine.classification, content)).strip()
        if not result:
            raise BuiltinOcrError("内置 OCR 没有识别出验证码")
        return result
