from __future__ import annotations

import time
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .client import TeachingClient, TeachingClientError
from .models import CourseMatch, CourseTarget, MatchKind
from .modules import MODULES


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    complete: bool
    message: str


class EnrollmentService:
    def __init__(self, client: TeachingClient) -> None:
        self.client = client

    async def enroll(self, match: CourseMatch) -> EnrollmentResult:
        if match.kind is MatchKind.ORDINARY and match.candidate:
            candidate = match.candidate
            params: dict[str, str | int] = {
                "kcid": candidate.course_id,
                "jx0404id": candidate.class_id,
                "_": int(time.time() * 1000),
            }
        elif match.kind is MatchKind.LECTURE_LAB and match.lecture and match.lab:
            candidate = match.lab
            params = {
                "kcid": candidate.course_id,
                "cfbs": "4",
                "yxcfbs": "1",
                "yxjx0404id": match.lecture.class_id,
                "cfmyz": "1",
                "jx0404id": candidate.class_id,
                "xkzy": "",
                "trjf": "",
            }
        else:
            raise ValueError("只有唯一可选候选可以提交")
        spec = MODULES[candidate.module]
        response = await self.client.request(
            "GET",
            f"/jsxsd/xsxkkc/{spec.operation}",
            params=params,
            headers={
                "Accept": "*/*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{self.client.base_url}/jsxsd/xsxkkc/{spec.entry}",
            },
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise TeachingClientError("选课响应不是有效 JSON") from exc
        message = str(payload.get("message", "未知响应"))
        return EnrollmentResult(complete=message == "选课成功", message=message)

    async def verify(self, target: CourseTarget, term_id: str) -> bool:
        page = await self.client.request("GET", "/jsxsd/xkgl/xsxkjgcx")
        page.raise_for_status()
        response = await self.client.request(
            "POST",
            "/jsxsd/xkgl/loadXsxkjgList",
            data={"xnxqid": term_id},
            headers={"Referer": f"{self.client.base_url}/jsxsd/xkgl/xsxkjgcx"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.select("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            if len(cells) < 10:
                continue
            name, code = cells[1], cells[2]
            if target.course_code and code == target.course_code:
                return True
            if target.course_name and target.course_name in name:
                return True
        return False
