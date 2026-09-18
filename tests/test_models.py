import pytest
from pydantic import ValidationError

from qfnu_course_web.models import CourseTarget, RuntimeConfig
from qfnu_course_web.modules import MODULES


def test_all_documented_modules_are_mapped() -> None:
    assert set(MODULES) == {"bxxk", "xxxk", "bxqjhxk", "knjxk", "fawxk", "ggxxkxk"}
    assert MODULES["knjxk"].operation == "knjxkOper"
    assert MODULES["ggxxkxk"].search == "xsxkGgxxkxk"


def test_runtime_rate_is_capped_at_five_requests_per_second() -> None:
    assert RuntimeConfig().requests_per_second == 5
    assert RuntimeConfig(requests_per_second=5).requests_per_second == 5
    with pytest.raises(ValidationError):
        RuntimeConfig(requests_per_second=5.01)


def test_target_requires_a_course_identifier() -> None:
    with pytest.raises(ValidationError):
        CourseTarget(module="xxxk")


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RuntimeConfig(unknown_setting=True)


def test_advanced_target_requires_only_a_course_code() -> None:
    target = CourseTarget(mode="advanced", module="xxxk", course_code="G200511771")
    assert target.mode == "advanced"
    with pytest.raises(ValidationError, match="高级模式"):
        CourseTarget(mode="advanced", module="xxxk", course_name="案例刑法")
