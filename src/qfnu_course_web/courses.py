from __future__ import annotations

import re
from html import unescape

from .client import TeachingClient, TeachingClientError
from .models import CourseCandidate, CourseMatch, CourseQuery, CourseTarget, MatchKind
from .modules import MODULES
from .rounds import RoundOption, parse_rounds


class ModuleUnavailableError(TeachingClientError):
    def __init__(self, module: str, label: str) -> None:
        super().__init__(f"当前轮次暂未开放{label}")
        self.module = module
        self.label = label


def parse_round_ids(html: str) -> list[str]:
    return [item.id for item in parse_rounds(html)]


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    return re.sub(r"\s*<br\s*/?>\s*", " / ", text, flags=re.I).strip()


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _selected(row: dict[str, object]) -> bool:
    explicit = row.get("selected") or row.get("sfxz") or row.get("yixuan")
    if explicit is True or str(explicit).strip().lower() in {"1", "true", "yes"}:
        return True
    operation = _clean(row.get("czOper"))
    return "已选" in operation


def parse_candidate(module: str, row: dict[str, object]) -> CourseCandidate:
    return CourseCandidate(
        module=module,
        course_id=_clean(row.get("jx02id")),
        course_code=_clean(row.get("kch")),
        course_name=_clean(row.get("kcmc")),
        class_id=_clean(row.get("jx0404id")),
        teacher=_clean(row.get("skls")),
        remaining=_optional_int(row.get("syrs")),
        enrolled=_optional_int(row.get("xkrs")),
        capacity=_optional_int(row.get("xxrs") or row.get("pkrs")),
        schedule=_clean(row.get("sksj")),
        location=_clean(row.get("skdd")),
        campus=_clean(row.get("xqmc")),
        credits=_optional_float(row.get("xf")),
        department=_clean(row.get("dwmc")),
        category=_clean(row.get("szkcflmc")),
        conflict=_clean(row.get("ctsm")),
        selected=_selected(row),
        split_flag=_optional_int(row.get("cfbs")),
        parent_class_id=_clean(row.get("parentjx0404id")) or None,
        lab_group=_clean(row.get("fzmc")) or None,
    )


class CourseCatalog:
    def __init__(self, client: TeachingClient) -> None:
        self.client = client
        self.round_id: str | None = None

    async def list_rounds(self) -> list[RoundOption]:
        response = await self.client.request("GET", "/jsxsd/xsxk/xklc_list")
        response.raise_for_status()
        return parse_rounds(response.text)

    async def enter_round(self, round_id: str) -> None:
        response = await self.client.request(
            "GET", "/jsxsd/xsxk/xsxk_index", params={"jx0502zbid": round_id}
        )
        response.raise_for_status()
        self.round_id = round_id

    async def enter_module(self, module: str) -> None:
        spec = MODULES[module]
        response = await self.client.request("GET", f"/jsxsd/xsxkkc/{spec.entry}")
        if response.status_code == 404:
            raise ModuleUnavailableError(module, spec.label)
        response.raise_for_status()

    async def search(self, target: CourseTarget | CourseQuery) -> list[CourseCandidate]:
        spec = MODULES[target.module]
        course_query = target.course_code or target.course_name or target.course_id or ""
        params = {
            "kcxx": course_query,
            "skls": target.teacher or "",
            "sfym": "false",
            "sfct": "false",
            "sfxx": "true",
        }
        if target.weekday:
            params["skxq"] = target.weekday
        if target.periods:
            params["skjc"] = self._period_code(target.periods)
        response = await self.client.request(
            "POST",
            f"/jsxsd/xsxkkc/{spec.search}",
            params=params,
            data={"iDisplayStart": "0", "iDisplayLength": "10000"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.client.base_url}/jsxsd/xsxkkc/{spec.entry}",
            },
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        try:
            payload = response.json()
            rows = payload.get("aaData", [])
        except (ValueError, AttributeError) as exc:
            raise TeachingClientError("课程搜索响应不是有效 JSON") from exc
        if not isinstance(rows, list):
            raise TeachingClientError("课程搜索响应缺少 aaData")
        return [parse_candidate(target.module, row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _period_code(value: str) -> str:
        return {
            "1-2": "1-2-",
            "3-5": "3-4-5",
            "6-7": "6-7-",
            "8-9": "8-9-",
            "10-12": "10-11-12",
        }.get(value, value)


def _matches(target: CourseTarget, candidate: CourseCandidate) -> bool:
    return all(
        (
            not target.course_id or candidate.course_id == target.course_id,
            not target.course_code or candidate.course_code == target.course_code,
            not target.course_name or target.course_name in candidate.course_name,
            not target.class_id or candidate.class_id == target.class_id,
            not target.teacher or target.teacher in candidate.teacher,
            not target.weekday or target.weekday in candidate.schedule,
            not target.periods or target.periods in candidate.schedule,
        )
    )


def match_target(target: CourseTarget, candidates: list[CourseCandidate]) -> CourseMatch:
    matches = [candidate for candidate in candidates if _matches(target, candidate)]
    if not matches:
        return CourseMatch(kind=MatchKind.NO_MATCH, target_id=target.id, message="未找到匹配课程")
    eligible = [
        item for item in matches if not item.conflict and not item.selected and item.remaining != 0
    ]
    if not eligible:
        return CourseMatch(
            kind=MatchKind.BLOCKED,
            target_id=target.id,
            message="课程已满、存在冲突或已经选过",
        )
    split = any(item.split_flag in (1, 4) for item in eligible)
    if split:
        labs = [item for item in eligible if item.split_flag == 4]
        if target.lab_group:
            labs = [item for item in labs if item.lab_group == target.lab_group]
        pairs: list[tuple[CourseCandidate, CourseCandidate]] = []
        for lab in labs:
            for lecture in eligible:
                if (
                    lecture.split_flag == 1
                    and lecture.course_id == lab.course_id
                    and (not lab.parent_class_id or lab.parent_class_id == lecture.class_id)
                ):
                    pairs.append((lecture, lab))
        if len(pairs) == 1:
            lecture, lab = pairs[0]
            return CourseMatch(
                kind=MatchKind.LECTURE_LAB,
                target_id=target.id,
                message="讲课与实验班匹配完成",
                lecture=lecture,
                lab=lab,
            )
        return CourseMatch(
            kind=MatchKind.AMBIGUOUS, target_id=target.id, message="讲课或实验班不唯一"
        )
    if len(eligible) != 1:
        return CourseMatch(
            kind=MatchKind.AMBIGUOUS, target_id=target.id, message="匹配到多个教学班"
        )
    return CourseMatch(
        kind=MatchKind.ORDINARY,
        target_id=target.id,
        message="找到唯一可选教学班",
        candidate=eligible[0],
    )
