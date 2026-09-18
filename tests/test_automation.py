import asyncio
from datetime import UTC, datetime, time, timedelta

import pytest

from qfnu_course_web.auth import AuthResult, ManualCaptchaRequired
from qfnu_course_web.automation import AutomationController, AutomationError
from qfnu_course_web.config import AppConfig
from qfnu_course_web.models import AutomationPhase, SchedulerPhase
from qfnu_course_web.rounds import RoundOption
from qfnu_course_web.state import AppState


class FakeAuth:
    def __init__(self, *, manual: bool = False) -> None:
        self.manual = manual
        self.automatic_calls = 0
        self.manual_codes: list[str] = []
        self.session_checks = 0

    async def check_session(self) -> bool:
        self.session_checks += 1
        return True

    async def automatic_login(self, username, password, ocr_url, *, attempts):
        self.automatic_calls += 1
        if self.manual:
            self.manual = False
            raise ManualCaptchaRequired("data:image/png;base64,YQ==")
        return AuthResult(authenticated=True, username=username)

    async def complete_login(self, username, password, captcha):
        self.manual_codes.append(captcha)
        return AuthResult(authenticated=True, username=username)


class FakeKeychain:
    def read(self, username: str) -> str:
        return "password"


class FakeCatalog:
    async def list_rounds(self):
        return [
            RoundOption(id="normal", name="2026 春季正选"),
            RoundOption(id="extra", name="2026 春季补选"),
        ]


class FakeScheduler:
    def __init__(self) -> None:
        self.starts = []
        self.stopped = False
        self.reauthenticate = None
        self.resolve_round = None

    def set_reauthenticate(self, callback):
        self.reauthenticate = callback

    def set_round_resolver(self, callback):
        self.resolve_round = callback

    async def start(self, runtime, targets):
        self.starts.append((runtime, targets))
        return asyncio.create_task(asyncio.sleep(0))

    async def stop(self):
        self.stopped = True


class StoppingScheduler(FakeScheduler):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state

    async def start(self, runtime, targets):
        self.starts.append((runtime, targets))

        async def stop_run():
            await self.state.set_scheduler(SchedulerPhase.STOPPED)

        return asyncio.create_task(stop_run())


def config_at(start_time: time | None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "account": {"username": "2024000000"},
            "auth": {"ocr_url": "http://ocr.local", "keepalive_seconds": 30},
            "selection": {
                "round_keywords": ["补选", "正选"],
                "start_time": start_time.isoformat() if start_time else None,
                "term_id": "term-1",
            },
            "targets": [{"module": "xxxk", "course_code": "001"}],
        }
    )


@pytest.mark.asyncio
async def test_automation_rejects_a_start_time_that_has_passed() -> None:
    now = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
    controller = AutomationController(
        AppState(), FakeAuth(), FakeKeychain(), FakeCatalog(), FakeScheduler(), now=lambda: now
    )

    with pytest.raises(AutomationError, match="已经过去"):
        await controller.start(config_at(time(9, 59)))


@pytest.mark.asyncio
async def test_automation_logs_in_selects_round_and_waits_until_start() -> None:
    current = datetime(2026, 9, 18, 9, 59, 58, tzinfo=UTC)
    state = AppState()
    auth = FakeAuth()
    scheduler = FakeScheduler()

    def now() -> datetime:
        return current

    async def sleep(delay: float) -> None:
        nonlocal current
        current += timedelta(seconds=delay)

    controller = AutomationController(
        state,
        auth,
        FakeKeychain(),
        FakeCatalog(),
        scheduler,
        now=now,
        sleep=sleep,
    )
    task = await controller.start(config_at(time(10, 0)))
    await task

    assert auth.automatic_calls == 1
    assert state.snapshot.round_id == "extra"
    assert state.snapshot.round_name == "2026 春季补选"
    assert scheduler.starts[0][0].round_id == "extra"
    assert state.snapshot.automation is AutomationPhase.COMPLETE
    assert state.snapshot.scheduler is SchedulerPhase.COMPLETE
    assert scheduler.reauthenticate is not None
    assert scheduler.resolve_round is not None


@pytest.mark.asyncio
async def test_automation_waits_until_a_round_appears() -> None:
    class AppearingRoundCatalog:
        def __init__(self) -> None:
            self.calls = 0

        async def list_rounds(self):
            self.calls += 1
            if self.calls == 1:
                return []
            return [RoundOption(id="current", name="当前轮次")]

    state = AppState()
    scheduler = FakeScheduler()
    controller = AutomationController(
        state,
        FakeAuth(),
        FakeKeychain(),
        AppearingRoundCatalog(),
        scheduler,
        sleep=lambda delay: asyncio.sleep(0),
    )

    config = config_at(None)
    config = config.model_copy(
        update={"selection": config.selection.model_copy(update={"round_keywords": []})}
    )
    task = await controller.start(config)
    await asyncio.wait_for(task, timeout=1)

    assert state.snapshot.round_id == "current"
    assert scheduler.starts[0][0].round_id == "current"
    assert any("暂无可用选课轮次" in event.message for event in state.snapshot.events)
    assert any("检测到可用轮次" in event.message for event in state.snapshot.events)


@pytest.mark.asyncio
async def test_automation_updates_the_current_round_while_waiting() -> None:
    class ChangingRoundsCatalog:
        def __init__(self) -> None:
            self.calls = 0

        async def list_rounds(self):
            self.calls += 1
            if self.calls == 1:
                return [RoundOption(id="old", name="旧轮次")]
            return [RoundOption(id="current", name="当前轮次")]

    current = datetime(2026, 9, 18, 9, 59, 58, tzinfo=UTC)

    async def sleep(delay: float) -> None:
        nonlocal current
        current += timedelta(seconds=delay)

    config = config_at(time(10, 0))
    config = config.model_copy(
        update={"selection": config.selection.model_copy(update={"round_keywords": []})}
    )
    state = AppState()
    scheduler = FakeScheduler()
    controller = AutomationController(
        state,
        FakeAuth(),
        FakeKeychain(),
        ChangingRoundsCatalog(),
        scheduler,
        now=lambda: current,
        sleep=sleep,
    )

    task = await controller.start(config)
    await task

    assert scheduler.starts[0][0].round_id == "current"
    assert state.snapshot.round_id == "current"


@pytest.mark.asyncio
async def test_automation_can_start_without_a_term_id() -> None:
    config = config_at(None)
    config = config.model_copy(
        update={"selection": config.selection.model_copy(update={"term_id": None})}
    )
    scheduler = FakeScheduler()
    controller = AutomationController(
        AppState(), FakeAuth(), FakeKeychain(), FakeCatalog(), scheduler
    )

    task = await controller.start(config)
    await task

    assert scheduler.starts[0][0].term_id is None


@pytest.mark.asyncio
async def test_scheduler_reauthentication_uses_the_automation_login_flow() -> None:
    state = AppState()
    auth = FakeAuth()
    scheduler = FakeScheduler()
    controller = AutomationController(state, auth, FakeKeychain(), FakeCatalog(), scheduler)
    task = await controller.start(config_at(None))
    await task

    state.snapshot.authenticated = False
    recovered = await scheduler.reauthenticate()

    assert recovered is True
    assert auth.automatic_calls == 2
    assert state.snapshot.authenticated is True


@pytest.mark.asyncio
async def test_stopped_scheduler_marks_automation_as_needing_attention() -> None:
    state = AppState()
    controller = AutomationController(
        state,
        FakeAuth(),
        FakeKeychain(),
        FakeCatalog(),
        StoppingScheduler(state),
    )

    task = await controller.start(config_at(None))
    await task

    assert state.snapshot.automation is AutomationPhase.NEEDS_ATTENTION


@pytest.mark.asyncio
async def test_automation_waits_for_a_manual_captcha_then_resumes() -> None:
    state = AppState()
    auth = FakeAuth(manual=True)
    scheduler = FakeScheduler()
    controller = AutomationController(state, auth, FakeKeychain(), FakeCatalog(), scheduler)

    task = await controller.start(config_at(None))
    for _ in range(20):
        if state.snapshot.automation is AutomationPhase.NEEDS_CAPTCHA:
            break
        await asyncio.sleep(0)

    assert state.snapshot.captcha_data_url
    await controller.submit_captcha("abcd")
    await task

    assert auth.manual_codes == ["abcd"]
    assert scheduler.starts


@pytest.mark.asyncio
async def test_automation_keeps_the_session_alive_while_waiting() -> None:
    current = datetime(2026, 9, 18, 9, 59, 29, tzinfo=UTC)
    auth = FakeAuth()

    async def sleep(delay: float) -> None:
        nonlocal current
        current += timedelta(seconds=delay)

    controller = AutomationController(
        AppState(),
        auth,
        FakeKeychain(),
        FakeCatalog(),
        FakeScheduler(),
        now=lambda: current,
        sleep=sleep,
    )
    task = await controller.start(config_at(time(10, 0)))
    await task

    assert auth.session_checks >= 1


@pytest.mark.asyncio
async def test_automation_stop_interrupts_a_scheduled_run() -> None:
    now = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
    state = AppState()
    scheduler = FakeScheduler()
    blocker = asyncio.Event()

    async def sleep(delay: float) -> None:
        await blocker.wait()

    controller = AutomationController(
        state,
        FakeAuth(),
        FakeKeychain(),
        FakeCatalog(),
        scheduler,
        now=lambda: now,
        sleep=sleep,
    )
    task = await controller.start(config_at(time(10, 0)))
    for _ in range(20):
        if state.snapshot.scheduler is SchedulerPhase.SCHEDULED:
            break
        await asyncio.sleep(0)

    await controller.stop()

    assert task.done()
    assert scheduler.stopped is True
    assert state.snapshot.scheduler is SchedulerPhase.STOPPED
