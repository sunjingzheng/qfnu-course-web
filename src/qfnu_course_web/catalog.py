from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from .client import RateLimitedError, RemoteLoginError, SessionExpiredError
from .courses import CourseCatalog
from .models import CourseCandidate, CourseQuery, CourseTarget
from .modules import MODULES


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogResult:
    candidates: list[CourseCandidate]
    module_counts: dict[str, int]
    module_errors: dict[str, str]
    loaded_at: datetime


class CatalogService:
    def __init__(self, source: CourseCatalog) -> None:
        self.source = source
        self._candidates: dict[str, CourseCandidate] = {}

    def clear(self) -> None:
        self._candidates.clear()

    def replace(self, candidates: list[CourseCandidate]) -> list[CourseCandidate]:
        self.clear()
        result: list[CourseCandidate] = []
        for candidate in candidates:
            catalog_id = candidate.catalog_id or uuid4().hex
            stored = candidate.model_copy(update={"catalog_id": catalog_id})
            self._candidates[catalog_id] = stored
            result.append(stored)
        return result

    async def load(self, round_id: str) -> CatalogResult:
        await self.source.enter_round(round_id)
        candidates: list[CourseCandidate] = []
        module_counts: dict[str, int] = {}
        module_errors: dict[str, str] = {}
        for module in MODULES:
            try:
                await self.source.enter_module(module)
                rows = await self.source.search(CourseQuery(module=module))
            except (RateLimitedError, RemoteLoginError, SessionExpiredError):
                raise
            except Exception as exc:
                rows = []
                module_errors[module] = str(exc)
            module_counts[module] = len(rows)
            candidates.extend(rows)
        stored = self.replace(candidates)
        return CatalogResult(
            candidates=stored,
            module_counts=module_counts,
            module_errors=module_errors,
            loaded_at=datetime.now(UTC),
        )

    def target_from_candidate(
        self, catalog_id: str, priority: int, targets: list[CourseTarget]
    ) -> CourseTarget:
        candidate = self._candidates.get(catalog_id)
        if candidate is None:
            raise CatalogError("课程目录记录已失效，请重新加载")
        if not candidate.course_id or not candidate.class_id:
            raise CatalogError("课程记录缺少选课标识")
        if candidate.split_flag == 1:
            raise CatalogError("该课程包含实验学时，请选择具体实验分组")
        if candidate.split_flag == 4:
            if not candidate.lab_group:
                raise CatalogError("实验课程缺少分组信息")
            target = CourseTarget(
                module=candidate.module,
                course_id=candidate.course_id,
                course_code=candidate.course_code or None,
                course_name=self._base_course_name(candidate.course_name) or None,
                lab_group=candidate.lab_group,
                priority=priority,
            )
        else:
            target = CourseTarget(
                module=candidate.module,
                course_id=candidate.course_id,
                course_code=candidate.course_code or None,
                course_name=candidate.course_name or None,
                class_id=candidate.class_id,
                teacher=candidate.teacher or None,
                priority=priority,
            )
        if any(self._same_target(target, existing) for existing in targets):
            raise CatalogError("该课程已经添加到监控")
        return target

    @staticmethod
    def _base_course_name(value: str) -> str:
        return re.sub(r"\s*\[(?:讲课|实验)学时\]\s*", "", value).strip()

    @staticmethod
    def _same_target(left: CourseTarget, right: CourseTarget) -> bool:
        if left.module != right.module:
            return False
        if left.lab_group or right.lab_group:
            return bool(
                left.course_id
                and left.course_id == right.course_id
                and left.lab_group
                and left.lab_group == right.lab_group
            )
        return bool(left.class_id and left.class_id == right.class_id)
