import pytest

from qfnu_course_web.catalog import CatalogError, CatalogService
from qfnu_course_web.client import TeachingClientError
from qfnu_course_web.models import CourseCandidate, CourseQuery
from qfnu_course_web.modules import MODULES


class FakeCourseCatalog:
    def __init__(self, *, failing_module: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.failing_module = failing_module

    async def enter_round(self, round_id: str) -> None:
        self.calls.append(("round", round_id))

    async def enter_module(self, module: str) -> None:
        self.calls.append(("module", module))

    async def search(self, query: CourseQuery) -> list[CourseCandidate]:
        self.calls.append(("search", query.module))
        if query.module == self.failing_module:
            raise TeachingClientError("模块暂不可用")
        return [
            CourseCandidate(
                module=query.module,
                course_id=f"course-{query.module}",
                course_code=f"code-{query.module}",
                course_name=f"课程 {query.module}",
                class_id=f"class-{query.module}",
            )
        ]


@pytest.mark.asyncio
async def test_catalog_loads_every_module_and_keeps_partial_errors() -> None:
    source = FakeCourseCatalog(failing_module="fawxk")
    service = CatalogService(source)

    result = await service.load("round-1")

    assert source.calls[0] == ("round", "round-1")
    assert [call for call in source.calls if call[0] == "module"] == [
        ("module", module) for module in MODULES
    ]
    assert len(result.candidates) == len(MODULES) - 1
    assert all(candidate.catalog_id for candidate in result.candidates)
    assert result.module_errors == {"fawxk": "模块暂不可用"}
    assert result.module_counts["fawxk"] == 0


def test_catalog_converts_an_ordinary_candidate_and_rejects_duplicates() -> None:
    service = CatalogService(FakeCourseCatalog())
    candidate = CourseCandidate(
        catalog_id="candidate-1",
        module="xxxk",
        course_id="course-1",
        course_code="001",
        course_name="大学语文",
        class_id="class-1",
        teacher="张老师",
    )
    service.replace([candidate])

    target = service.target_from_candidate("candidate-1", 20, [])

    assert target.class_id == "class-1"
    assert target.course_name == "大学语文"
    with pytest.raises(CatalogError, match="已经添加"):
        service.target_from_candidate("candidate-1", 20, [target])


def test_catalog_requires_an_experiment_group_for_split_courses() -> None:
    service = CatalogService(FakeCourseCatalog())
    lecture = CourseCandidate(
        catalog_id="lecture",
        module="knjxk",
        course_id="course-1",
        course_code="301043",
        course_name="电子测量[讲课学时]",
        class_id="lecture-1",
        split_flag=1,
    )
    lab = CourseCandidate(
        catalog_id="lab",
        module="knjxk",
        course_id="course-1",
        course_code="301043",
        course_name="电子测量[实验学时]",
        class_id="lab-1",
        split_flag=4,
        parent_class_id="lecture-1",
        lab_group="分组02",
    )
    service.replace([lecture, lab])

    with pytest.raises(CatalogError, match="实验分组"):
        service.target_from_candidate("lecture", 100, [])
    target = service.target_from_candidate("lab", 100, [])

    assert target.course_name == "电子测量"
    assert target.class_id is None
    assert target.lab_group == "分组02"


def test_catalog_rejects_an_unknown_or_incomplete_candidate() -> None:
    service = CatalogService(FakeCourseCatalog())
    service.replace(
        [CourseCandidate(catalog_id="incomplete", module="xxxk", course_name="未知课程")]
    )
    with pytest.raises(CatalogError, match="目录记录已失效"):
        service.target_from_candidate("missing", 100, [])
    with pytest.raises(CatalogError, match="缺少选课标识"):
        service.target_from_candidate("incomplete", 100, [])
