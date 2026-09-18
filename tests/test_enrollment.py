import httpx
import pytest

from qfnu_course_web.client import TeachingClient
from qfnu_course_web.enrollment import EnrollmentService
from qfnu_course_web.models import CourseCandidate, CourseMatch, CourseTarget, MatchKind


class NoWaitLimiter:
    async def acquire(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ordinary_and_split_enrollment_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"success": True, "message": "选课成功"})

    client = TeachingClient(transport=httpx.MockTransport(handler), limiter=NoWaitLimiter())
    service = EnrollmentService(client)
    ordinary = CourseCandidate(module="xxxk", course_id="c1", class_id="j1", course_name="课")
    result = await service.enroll(
        CourseMatch(kind=MatchKind.ORDINARY, target_id="t", message="", candidate=ordinary)
    )
    assert result.complete is True
    assert set(requests[-1].url.params) == {"kcid", "jx0404id", "_"}

    lecture = ordinary.model_copy(
        update={"module": "knjxk", "class_id": "lecture", "split_flag": 1}
    )
    lab = lecture.model_copy(update={"class_id": "lab", "split_flag": 4, "lab_group": "分组01"})
    await service.enroll(
        CourseMatch(
            kind=MatchKind.LECTURE_LAB,
            target_id="t",
            message="",
            lecture=lecture,
            lab=lab,
        )
    )
    params = requests[-1].url.params
    assert params["yxjx0404id"] == "lecture"
    assert params["jx0404id"] == "lab"
    assert params["cfbs"] == "4"
    assert params["cfmyz"] == "1"
    await client.close()


@pytest.mark.asyncio
async def test_result_table_verifies_course() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("xsxkjgcx"):
            return httpx.Response(200, text="page")
        cells = "".join(
            f"<td>{value}</td>"
            for value in ["1", "大学语文", "001", "李老师", "", "2", "", "", "", "2026-09-17"]
        )
        return httpx.Response(200, text=f"<table><tr>{cells}</tr></table>")

    client = TeachingClient(transport=httpx.MockTransport(handler), limiter=NoWaitLimiter())
    target = CourseTarget(module="xxxk", course_code="001")
    assert await EnrollmentService(client).verify(target, "2026-1") is True
    await client.close()
