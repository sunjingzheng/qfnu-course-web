import httpx
import pytest

from qfnu_course_web.client import TeachingClient
from qfnu_course_web.courses import (
    CourseCatalog,
    ModuleUnavailableError,
    match_target,
    parse_round_ids,
)
from qfnu_course_web.models import CourseQuery, CourseTarget, MatchKind


class NoWaitLimiter:
    async def acquire(self) -> None:
        return None


def test_parse_round_ids_from_links_and_javascript() -> None:
    html = """
    <a href='/jsxsd/xsxk/xsxk_index?jx0502zbid=round-a'>A</a>
    <button onclick="jrxk('round-b')">B</button>
    """
    assert parse_round_ids(html) == ["round-a", "round-b"]


@pytest.mark.asyncio
async def test_search_parses_candidate_and_sends_large_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/xsxkKnjxk")
        assert request.url.params["kcxx"] == "301043"
        assert request.url.params["sfxx"] == "false"
        assert dict(httpx.QueryParams(request.content.decode()))["iDisplayLength"] == "10000"
        return httpx.Response(
            200,
            json={
                "aaData": [
                    {
                        "kch": "301043",
                        "kcmc": "电子测量[实验学时]",
                        "skls": "李老师",
                        "syrs": "25",
                        "jx0404id": "lab-1",
                        "jx02id": "course-1",
                        "cfbs": 4,
                        "parentjx0404id": "lecture-1",
                        "fzmc": "分组01",
                        "sksj": "周六<br>1-2节",
                        "skdd": "C609<br>C611",
                        "ctsm": "",
                        "xf": "2.5",
                        "dwmc": "物理工程学院",
                        "szkcflmc": "专业教育",
                    }
                ]
            },
        )

    client = TeachingClient(transport=httpx.MockTransport(handler), limiter=NoWaitLimiter())
    rows = await CourseCatalog(client).search(
        CourseTarget(module="knjxk", course_code="301043", lab_group="分组01")
    )
    assert rows[0].remaining == 25
    assert rows[0].schedule == "周六 / 1-2节"
    assert rows[0].location == "C609 / C611"
    assert rows[0].credits == 2.5
    assert rows[0].department == "物理工程学院"
    assert rows[0].category == "专业教育"
    await client.close()


def test_course_query_allows_an_empty_catalog_filter() -> None:
    query = CourseQuery(module="ggxxkxk")
    assert query.course_code is None
    assert query.teacher is None


@pytest.mark.asyncio
async def test_enter_module_classifies_a_missing_round_module() -> None:
    client = TeachingClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
        limiter=NoWaitLimiter(),
    )

    with pytest.raises(ModuleUnavailableError, match="公选课选课"):
        await CourseCatalog(client).enter_module("ggxxkxk")


@pytest.mark.asyncio
async def test_search_classifies_a_missing_round_module() -> None:
    client = TeachingClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )

    with pytest.raises(ModuleUnavailableError, match="选修选课"):
        await CourseCatalog(client).search(CourseTarget(module="xxxk", course_code="302752"))

    await client.close()


@pytest.mark.asyncio
async def test_empty_catalog_query_filters_to_the_students_allowed_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["kcxx"] == ""
        assert request.url.params["sfxx"] == "true"
        return httpx.Response(200, json={"aaData": []})

    client = TeachingClient(transport=httpx.MockTransport(handler), limiter=NoWaitLimiter())
    rows = await CourseCatalog(client).search(CourseQuery(module="knjxk"))
    assert rows == []
    await client.close()


@pytest.mark.asyncio
async def test_course_code_mode_requests_server_side_full_and_conflict_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["kcxx"] == "G200511771"
        assert request.url.params["sfym"] == "true"
        assert request.url.params["sfct"] == "true"
        return httpx.Response(200, json={"aaData": []})

    client = TeachingClient(transport=httpx.MockTransport(handler), limiter=NoWaitLimiter())
    target = CourseTarget(mode="advanced", module="xxxk", course_code="G200511771")

    assert await CourseCatalog(client).search(target) == []
    await client.close()


def test_match_pairs_lecture_and_requested_lab() -> None:
    from qfnu_course_web.models import CourseCandidate

    target = CourseTarget(module="knjxk", course_code="301043", lab_group="分组02")
    base = {"module": "knjxk", "course_id": "course-1", "course_code": "301043", "remaining": 4}
    candidates = [
        CourseCandidate(**base, course_name="电子测量[讲课学时]", class_id="lecture", split_flag=1),
        CourseCandidate(
            **base,
            course_name="电子测量[实验学时]",
            class_id="lab-1",
            split_flag=4,
            parent_class_id="lecture",
            lab_group="分组01",
        ),
        CourseCandidate(
            **base,
            course_name="电子测量[实验学时]",
            class_id="lab-2",
            split_flag=4,
            parent_class_id="lecture",
            lab_group="分组02",
        ),
    ]
    match = match_target(target, candidates)
    assert match.kind is MatchKind.LECTURE_LAB
    assert match.lecture.class_id == "lecture"
    assert match.lab.class_id == "lab-2"


def test_match_blocks_conflicts_and_ambiguity() -> None:
    from qfnu_course_web.models import CourseCandidate

    target = CourseTarget(module="xxxk", course_name="大学语文")
    conflict = CourseCandidate(
        module="xxxk", course_id="1", class_id="1", course_name="大学语文", conflict="时间冲突"
    )
    assert match_target(target, [conflict]).kind is MatchKind.BLOCKED
    ordinary = conflict.model_copy(update={"conflict": "", "remaining": 3})
    second = ordinary.model_copy(update={"class_id": "2"})
    assert match_target(target, [ordinary, second]).kind is MatchKind.AMBIGUOUS


def test_parse_candidate_marks_an_already_selected_operation() -> None:
    from qfnu_course_web.courses import parse_candidate

    candidate = parse_candidate(
        "xxxk",
        {
            "kch": "G200511771",
            "jx02id": "course",
            "jx0404id": "class",
            "czOper": '<span class="muted">已选</span>',
        },
    )

    assert candidate.selected is True
