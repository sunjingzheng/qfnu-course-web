import asyncio

import pytest

from qfnu_course_web.client import SessionExpiredError
from qfnu_course_web.courses import ModuleUnavailableError
from qfnu_course_web.enrollment import EnrollmentResult
from qfnu_course_web.models import (
    CourseCandidate,
    CourseTarget,
    RuntimeConfig,
    SchedulerPhase,
    TaskPhase,
)
from qfnu_course_web.rounds import RoundOption, RoundSelectionError
from qfnu_course_web.scheduler import CourseScheduler
from qfnu_course_web.state import AppState


class FakeCatalog:
    calls = 0

    async def list_rounds(self) -> list[str]:
        return ["round-1"]

    async def enter_round(self, round_id: str) -> None:
        return None

    async def enter_module(self, module: str) -> None:
        return None

    async def search(self, target: CourseTarget) -> list[CourseCandidate]:
        self.calls += 1
        return [
            CourseCandidate(
                module=target.module,
                course_id="course",
                course_code=target.course_code or "001",
                course_name="大学语文",
                class_id="class",
                remaining=1,
            )
        ]


class FakeEnrollment:
    enroll_calls = 0

    async def enroll(self, match):
        self.enroll_calls += 1
        return EnrollmentResult(True, "选课成功")

    async def verify(self, target: CourseTarget, term_id: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_scheduler_is_idempotent_and_stops_after_success() -> None:
    state = AppState()
    catalog = FakeCatalog()
    enrollment = FakeEnrollment()
    scheduler = CourseScheduler(state, catalog, enrollment, sleep=lambda delay: asyncio.sleep(0))
    target = CourseTarget(module="xxxk", course_code="001")
    config = RuntimeConfig(round_id="round-1", term_id="term", poll_interval_seconds=0.5)
    first = await scheduler.start(config, [target])
    second = await scheduler.start(config, [target])
    assert first is second
    await asyncio.wait_for(first, timeout=1)
    assert catalog.calls == 1
    assert enrollment.enroll_calls == 1
    assert state.snapshot.scheduler is SchedulerPhase.COMPLETE
    assert state.snapshot.statuses[0].phase.value == "success"


@pytest.mark.asyncio
async def test_scheduler_runs_without_term_id_and_does_not_skip_exclusive_group() -> None:
    class NoVerificationEnrollment(FakeEnrollment):
        def __init__(self) -> None:
            self.enroll_calls = 0

        async def verify(self, target, term_id):
            raise AssertionError("result verification requires a term id")

    state = AppState()
    enrollment = NoVerificationEnrollment()
    scheduler = CourseScheduler(
        state, FakeCatalog(), enrollment, sleep=lambda delay: asyncio.sleep(0)
    )
    targets = [
        CourseTarget(module="xxxk", course_code="001", exclusive_group="one", priority=1),
        CourseTarget(module="xxxk", course_code="002", exclusive_group="one", priority=2),
    ]

    task = await scheduler.start(RuntimeConfig(round_id="round-1"), targets)
    await asyncio.wait_for(task, timeout=1)

    assert enrollment.enroll_calls == 2
    assert all(status.phase is TaskPhase.SUCCESS for status in state.snapshot.statuses)
    assert all("未二次确认" in status.message for status in state.snapshot.statuses)


@pytest.mark.asyncio
async def test_new_subscriber_receives_snapshot_first() -> None:
    state = AppState()
    queue = await state.subscribe()
    message = await queue.get()
    assert message[0] == "snapshot"
    await state.add_event("info", "test", "hello")
    message = await queue.get()
    assert message[0] == "event"


@pytest.mark.asyncio
async def test_advanced_target_searches_by_code_and_filters_unavailable_classes() -> None:
    class CapturingEnrollment(FakeEnrollment):
        def __init__(self):
            self.matches = []

        async def enroll(self, match):
            self.matches.append(match)
            return EnrollmentResult(
                len(self.matches) == 2, "选课成功" if len(self.matches) == 2 else "未选中"
            )

    class MultipleCatalog(FakeCatalog):
        async def search(self, target):
            base = {
                "module": target.module,
                "course_id": "course-id",
                "course_code": target.course_code,
                "course_name": "案例刑法（在线课）",
                "remaining": 2,
            }
            return [
                CourseCandidate(**base, class_id="conflict", conflict="时间冲突"),
                CourseCandidate(**base, class_id="selected", selected=True),
                CourseCandidate(**base, class_id="class-1"),
                CourseCandidate(**base, class_id="class-2"),
            ]

    state = AppState()
    enrollment = CapturingEnrollment()
    scheduler = CourseScheduler(
        state, MultipleCatalog(), enrollment, sleep=lambda delay: asyncio.sleep(0)
    )
    target = CourseTarget(mode="advanced", module="xxxk", course_code="G200511771")
    task = await scheduler.start(RuntimeConfig(round_id="round-1"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert [match.candidate.class_id for match in enrollment.matches] == ["class-1", "class-2"]


@pytest.mark.asyncio
async def test_unsuccessful_submission_keeps_requesting_until_success() -> None:
    class RetryEnrollment(FakeEnrollment):
        def __init__(self) -> None:
            self.enroll_calls = 0

        async def enroll(self, match):
            self.enroll_calls += 1
            if self.enroll_calls == 1:
                return EnrollmentResult(False, "暂未选中")
            return EnrollmentResult(True, "选课成功")

    enrollment = RetryEnrollment()
    scheduler = CourseScheduler(
        AppState(), FakeCatalog(), enrollment, sleep=lambda delay: asyncio.sleep(0)
    )
    target = CourseTarget(module="xxxk", course_code="001")

    task = await scheduler.start(RuntimeConfig(round_id="round-1"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert enrollment.enroll_calls == 2


@pytest.mark.asyncio
async def test_temporarily_missing_module_keeps_waiting_and_recovers() -> None:
    class RecoveringCatalog(FakeCatalog):
        def __init__(self) -> None:
            self.entry_attempts = 0
            self.calls = 0

        async def enter_module(self, module: str) -> None:
            self.entry_attempts += 1
            if self.entry_attempts == 1:
                raise ModuleUnavailableError(module, "公选课选课")

    state = AppState()
    catalog = RecoveringCatalog()
    enrollment = FakeEnrollment()
    scheduler = CourseScheduler(state, catalog, enrollment, sleep=lambda delay: asyncio.sleep(0))
    target = CourseTarget(mode="advanced", module="ggxxkxk", course_code="G200511771")

    task = await scheduler.start(RuntimeConfig(round_id="round-1"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert catalog.entry_attempts == 2
    assert enrollment.enroll_calls == 1
    assert state.snapshot.scheduler is SchedulerPhase.COMPLETE
    assert any("暂未开放公选课选课" in event.message for event in state.snapshot.events)


@pytest.mark.asyncio
async def test_search_404_invalidates_the_entered_module_before_retrying() -> None:
    class RecoveringCatalog(FakeCatalog):
        def __init__(self) -> None:
            self.entry_attempts = 0
            self.search_attempts = 0

        async def enter_module(self, module: str) -> None:
            self.entry_attempts += 1

        async def search(self, target):
            self.search_attempts += 1
            if self.search_attempts == 1:
                raise ModuleUnavailableError(target.module, "选修选课")
            return await super().search(target)

    state = AppState()
    catalog = RecoveringCatalog()
    scheduler = CourseScheduler(
        state, catalog, FakeEnrollment(), sleep=lambda delay: asyncio.sleep(0)
    )
    target = CourseTarget(module="xxxk", course_code="302752")

    task = await scheduler.start(RuntimeConfig(round_id="round-1"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert catalog.entry_attempts == 2
    assert state.snapshot.scheduler is SchedulerPhase.COMPLETE


@pytest.mark.asyncio
async def test_scheduler_reenters_when_switching_between_target_modules() -> None:
    class ContextSensitiveCatalog(FakeCatalog):
        def __init__(self) -> None:
            self.active_module = None
            self.entries = []
            self.searches = {"xxxk": 0, "knjxk": 0}

        async def enter_module(self, module: str) -> None:
            self.active_module = module
            self.entries.append(module)

        async def search(self, target):
            if self.active_module != target.module:
                raise ModuleUnavailableError(target.module, "模块上下文错误")
            self.searches[target.module] += 1
            if self.searches[target.module] == 1:
                return []
            return await super().search(target)

    state = AppState()
    catalog = ContextSensitiveCatalog()
    scheduler = CourseScheduler(
        state, catalog, FakeEnrollment(), sleep=lambda delay: asyncio.sleep(0)
    )
    targets = [
        CourseTarget(module="xxxk", course_code="302087", priority=1),
        CourseTarget(module="knjxk", course_code="307015", priority=2),
    ]

    task = await scheduler.start(RuntimeConfig(round_id="round-1"), targets)
    await asyncio.wait_for(task, timeout=1)

    assert catalog.entries == ["xxxk", "knjxk", "xxxk", "knjxk"]
    assert not any("模块上下文错误" in event.message for event in state.snapshot.events)


@pytest.mark.asyncio
async def test_advanced_course_code_pairs_lecture_and_lab_rows() -> None:
    class CapturingEnrollment(FakeEnrollment):
        def __init__(self):
            self.match = None

        async def enroll(self, match):
            self.match = match
            return EnrollmentResult(True, "选课成功")

    state = AppState()
    enrollment = CapturingEnrollment()

    class SplitCatalog(FakeCatalog):
        async def search(self, target):
            base = {
                "module": "knjxk",
                "course_id": "course-id",
                "course_code": target.course_code,
                "remaining": 2,
            }
            return [
                CourseCandidate(**base, class_id="lecture-id", split_flag=1),
                CourseCandidate(
                    **base,
                    class_id="lab-id",
                    split_flag=4,
                    parent_class_id="lecture-id",
                    lab_group="分组02",
                ),
            ]

    scheduler = CourseScheduler(
        state, SplitCatalog(), enrollment, sleep=lambda delay: asyncio.sleep(0)
    )
    target = CourseTarget(mode="advanced", module="knjxk", course_code="080001")
    task = await scheduler.start(RuntimeConfig(round_id="round-1", term_id="term"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert enrollment.match.lecture.class_id == "lecture-id"
    assert enrollment.match.lab.class_id == "lab-id"
    assert enrollment.match.lab.parent_class_id == "lecture-id"
    assert enrollment.match.lab.lab_group == "分组02"


@pytest.mark.asyncio
async def test_success_skips_other_targets_in_the_same_exclusive_group() -> None:
    state = AppState()
    catalog = FakeCatalog()
    enrollment = FakeEnrollment()
    scheduler = CourseScheduler(state, catalog, enrollment, sleep=lambda delay: asyncio.sleep(0))
    targets = [
        CourseTarget(module="xxxk", course_code="001", exclusive_group="language", priority=1),
        CourseTarget(module="xxxk", course_code="002", exclusive_group="language", priority=2),
    ]
    task = await scheduler.start(RuntimeConfig(round_id="round-1", term_id="term"), targets)
    await asyncio.wait_for(task, timeout=1)

    statuses = {item.target_id: item.phase for item in state.snapshot.statuses}
    assert statuses[targets[0].id] is TaskPhase.SUCCESS
    assert statuses[targets[1].id] is TaskPhase.SKIPPED


@pytest.mark.asyncio
async def test_session_expiry_reauthenticates_and_retries() -> None:
    class ExpiringCatalog(FakeCatalog):
        def __init__(self):
            self.searches = 0
            self.round_entries = 0

        async def enter_round(self, round_id):
            self.round_entries += 1

        async def search(self, target):
            self.searches += 1
            if self.searches == 1:
                raise SessionExpiredError("登录会话已失效")
            return await super().search(target)

    recovered = 0

    async def reauthenticate() -> bool:
        nonlocal recovered
        recovered += 1
        return True

    state = AppState()
    catalog = ExpiringCatalog()
    scheduler = CourseScheduler(
        state,
        catalog,
        FakeEnrollment(),
        sleep=lambda delay: asyncio.sleep(0),
        reauthenticate=reauthenticate,
    )
    target = CourseTarget(module="xxxk", course_code="001")
    task = await scheduler.start(RuntimeConfig(round_id="round-1", term_id="term"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert recovered == 1
    assert catalog.round_entries == 2
    assert state.snapshot.statuses[0].phase is TaskPhase.SUCCESS


@pytest.mark.asyncio
async def test_scheduler_switches_to_a_new_current_round_while_running() -> None:
    class ChangingCatalog(FakeCatalog):
        def __init__(self) -> None:
            self.searches = 0
            self.round_entries = []

        async def enter_round(self, round_id):
            self.round_entries.append(round_id)

        async def search(self, target):
            self.searches += 1
            if self.searches == 1:
                return []
            return await super().search(target)

    rounds = iter(
        [
            RoundOption(id="old", name="旧轮次"),
            RoundOption(id="old", name="旧轮次"),
            RoundOption(id="current", name="当前轮次"),
        ]
    )

    async def resolve_round():
        return next(rounds)

    state = AppState()
    catalog = ChangingCatalog()
    scheduler = CourseScheduler(
        state,
        catalog,
        FakeEnrollment(),
        sleep=lambda delay: asyncio.sleep(0),
        resolve_round=resolve_round,
    )
    target = CourseTarget(module="xxxk", course_code="001")

    task = await scheduler.start(RuntimeConfig(term_id="term"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert catalog.round_entries == ["old", "current"]
    assert state.snapshot.round_id == "current"
    assert state.snapshot.round_name == "当前轮次"


@pytest.mark.asyncio
async def test_scheduler_reenters_round_when_its_name_changes_with_the_same_id() -> None:
    class ChangingCatalog(FakeCatalog):
        def __init__(self) -> None:
            self.searches = 0
            self.round_entries = []
            self.module_entries = 0

        async def enter_round(self, round_id):
            self.round_entries.append(round_id)

        async def enter_module(self, module):
            self.module_entries += 1

        async def search(self, target):
            self.searches += 1
            if self.searches == 1:
                return []
            return await super().search(target)

    rounds = iter(
        [
            RoundOption(id="shared", name="退课轮次"),
            RoundOption(id="shared", name="退课轮次"),
            RoundOption(id="shared", name="选课轮次"),
        ]
    )

    async def resolve_round():
        return next(rounds)

    state = AppState()
    catalog = ChangingCatalog()
    scheduler = CourseScheduler(
        state,
        catalog,
        FakeEnrollment(),
        sleep=lambda delay: asyncio.sleep(0),
        resolve_round=resolve_round,
    )
    target = CourseTarget(module="xxxk", course_code="302752")

    task = await scheduler.start(RuntimeConfig(term_id="term"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert catalog.round_entries == ["shared", "shared"]
    assert catalog.module_entries == 2
    assert state.snapshot.round_name == "选课轮次"


@pytest.mark.asyncio
async def test_scheduler_stops_stale_requests_while_rounds_are_temporarily_empty() -> None:
    class ChangingCatalog(FakeCatalog):
        def __init__(self) -> None:
            self.calls = 0
            self.round_entries = []

        async def enter_round(self, round_id):
            self.round_entries.append(round_id)

    results = iter(
        [
            RoundOption(id="old", name="旧轮次"),
            RoundSelectionError("没有可用选课轮次"),
            RoundOption(id="current", name="当前轮次"),
        ]
    )

    async def resolve_round():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    state = AppState()
    catalog = ChangingCatalog()
    scheduler = CourseScheduler(
        state,
        catalog,
        FakeEnrollment(),
        sleep=lambda delay: asyncio.sleep(0),
        resolve_round=resolve_round,
    )
    target = CourseTarget(module="xxxk", course_code="001")

    task = await scheduler.start(RuntimeConfig(term_id="term"), [target])
    await asyncio.wait_for(task, timeout=1)

    assert catalog.calls == 1
    assert catalog.round_entries == ["old", "current"]
    assert state.snapshot.round_id == "current"
    assert state.snapshot.scheduler is SchedulerPhase.COMPLETE
    assert any("轮次列表暂时为空" in event.message for event in state.snapshot.events)
    assert any("轮次已恢复" in event.message for event in state.snapshot.events)


@pytest.mark.asyncio
async def test_scheduler_waits_if_round_disappears_during_startup() -> None:
    results = iter(
        [
            RoundSelectionError("没有可用选课轮次"),
            RoundOption(id="current", name="当前轮次"),
        ]
    )

    async def resolve_round():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    state = AppState()
    catalog = FakeCatalog()
    scheduler = CourseScheduler(
        state,
        catalog,
        FakeEnrollment(),
        sleep=lambda delay: asyncio.sleep(0),
        resolve_round=resolve_round,
    )
    target = CourseTarget(module="xxxk", course_code="001")

    task = await scheduler.start(RuntimeConfig(), [target])
    await asyncio.wait_for(task, timeout=1)

    assert catalog.calls == 1
    assert state.snapshot.round_id == "current"
    assert state.snapshot.scheduler is SchedulerPhase.COMPLETE
