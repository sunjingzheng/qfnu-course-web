from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta

from .auth import AuthService, ManualCaptchaRequired
from .client import SessionExpiredError
from .config import AppConfig
from .keychain import KeychainStore
from .models import AutomationPhase, RuntimeConfig, SchedulerPhase
from .rounds import RoundOption, RoundSelectionError, select_round
from .state import AppState


class AutomationError(RuntimeError):
    pass


class AutomationController:
    def __init__(
        self,
        state: AppState,
        auth: AuthService,
        keychain: KeychainStore,
        catalog: object,
        scheduler: object,
        *,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.state = state
        self.auth = auth
        self.keychain = keychain
        self.catalog = catalog
        self.scheduler = scheduler
        self.now = now
        self.sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._captcha_future: asyncio.Future[str] | None = None

    async def start(self, config: AppConfig) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            return self._task
        if not config.targets:
            raise AutomationError("请先添加目标课程")
        scheduled_for = self._scheduled_datetime(config)
        self._task = asyncio.create_task(self._run(config, scheduled_for), name="course-automation")
        return self._task

    async def stop(self) -> None:
        if self._captcha_future and not self._captcha_future.done():
            self._captcha_future.cancel()
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        await self.scheduler.stop()  # type: ignore[attr-defined]
        self.state.snapshot.scheduled_for = None
        self.state.snapshot.countdown_seconds = 0
        self.state.snapshot.automation = AutomationPhase.IDLE
        await self.state.set_scheduler(SchedulerPhase.STOPPED)

    async def submit_captcha(self, captcha: str) -> None:
        if not self._captcha_future or self._captcha_future.done():
            raise AutomationError("当前没有等待手动验证码的任务")
        value = captcha.strip()
        if not value:
            raise AutomationError("验证码不能为空")
        self._captcha_future.set_result(value)

    def _scheduled_datetime(self, config: AppConfig) -> datetime | None:
        start_time = config.selection.start_time
        if start_time is None:
            return None
        current = self.now()
        scheduled = datetime.combine(current.date(), start_time, tzinfo=current.tzinfo)
        if scheduled <= current:
            raise AutomationError("今天的开始时间已经过去，请修改后重试")
        return scheduled

    async def _run(self, config: AppConfig, scheduled_for: datetime | None) -> None:
        try:
            await self._ensure_authenticated(config)
            self.state.snapshot.automation = AutomationPhase.SELECTING_ROUND
            await self.state.publish_snapshot()
            selected = await self._wait_for_available_round(config)
            self.state.snapshot.round_id = selected.id
            self.state.snapshot.round_name = selected.name
            await self.state.add_event("info", "automation", f"已选择轮次：{selected.name}")
            if scheduled_for is not None:
                selected = await self._wait_until(config, scheduled_for, selected)
            runtime = RuntimeConfig(
                requests_per_second=config.selection.requests_per_second,
                poll_interval_seconds=config.selection.poll_interval_seconds,
                max_runtime_minutes=config.selection.max_runtime_minutes,
                round_id=selected.id,
                term_id=config.selection.term_id,
                ocr_url=config.auth.ocr_url,
            )
            self.state.snapshot.automation = AutomationPhase.RUNNING
            self.state.snapshot.scheduled_for = None
            self.state.snapshot.countdown_seconds = 0
            await self.state.publish_snapshot()
            self.scheduler.set_reauthenticate(  # type: ignore[attr-defined]
                lambda: self._recover_session(config)
            )
            self.scheduler.set_round_resolver(  # type: ignore[attr-defined]
                lambda: self._resolve_round(config)
            )
            scheduler_task = await self.scheduler.start(runtime, config.targets)  # type: ignore[attr-defined]
            await scheduler_task
            if self.state.snapshot.scheduler is SchedulerPhase.STOPPED:
                self.state.snapshot.automation = AutomationPhase.NEEDS_ATTENTION
                await self.state.publish_snapshot()
            else:
                self.state.snapshot.automation = AutomationPhase.COMPLETE
            if self.state.snapshot.scheduler in {
                SchedulerPhase.IDLE,
                SchedulerPhase.SCHEDULED,
                SchedulerPhase.RUNNING,
            }:
                await self.state.set_scheduler(SchedulerPhase.COMPLETE)
            elif self.state.snapshot.scheduler is not SchedulerPhase.STOPPED:
                await self.state.publish_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.snapshot.automation = AutomationPhase.NEEDS_ATTENTION
            await self.state.add_event("error", "automation", str(exc))
            await self.state.set_scheduler(SchedulerPhase.STOPPED)

    async def _ensure_authenticated(self, config: AppConfig) -> None:
        if self.state.snapshot.authenticated and await self.auth.check_session():
            return
        username = config.account.username.strip()
        if not username:
            raise AutomationError("请先配置学号")
        password = self.keychain.read(username)
        self.state.snapshot.automation = AutomationPhase.SIGNING_IN
        await self.state.publish_snapshot()
        try:
            result = await self.auth.automatic_login(
                username,
                password,
                config.auth.ocr_url,
                attempts=config.auth.ocr_attempts,
            )
        except ManualCaptchaRequired as exc:
            self.state.snapshot.automation = AutomationPhase.NEEDS_CAPTCHA
            self.state.snapshot.captcha_data_url = exc.captcha_data_url
            await self.state.add_event("warning", "auth", str(exc))
            await self.state.publish_snapshot()
            self._captcha_future = asyncio.get_running_loop().create_future()
            captcha = await self._captcha_future
            self._captcha_future = None
            result = await self.auth.complete_login(username, password, captcha)
        self.state.snapshot.authenticated = result.authenticated
        self.state.snapshot.username = result.username
        self.state.snapshot.captcha_data_url = None
        await self.state.add_event("success", "auth", "自动登录成功")
        await self.state.publish_snapshot()

    async def _recover_session(self, config: AppConfig) -> bool:
        self.state.snapshot.authenticated = False
        await self._ensure_authenticated(config)
        self.state.snapshot.automation = AutomationPhase.RUNNING
        await self.state.publish_snapshot()
        return self.state.snapshot.authenticated

    async def _resolve_round(self, config: AppConfig) -> RoundOption:
        rounds = await self.catalog.list_rounds()  # type: ignore[attr-defined]
        return select_round(rounds, config.selection.round_keywords)

    async def _wait_for_available_round(self, config: AppConfig) -> RoundOption:
        waiting = False
        while True:
            try:
                selected = await self._resolve_round(config)
                if waiting:
                    await self.state.add_event(
                        "success", "round", f"检测到可用轮次：{selected.name}"
                    )
                return selected
            except RoundSelectionError:
                self.state.snapshot.round_id = None
                self.state.snapshot.round_name = None
                if not waiting:
                    waiting = True
                    await self.state.add_event("warning", "round", "暂无可用选课轮次，正在持续监听")
                    await self.state.publish_snapshot()
                await self.sleep(1)
            except SessionExpiredError as exc:
                await self.state.add_event("warning", "session", str(exc))
                recovered = await self._recover_session(config)
                if not recovered:
                    raise
                self.state.snapshot.automation = AutomationPhase.SELECTING_ROUND
                await self.state.add_event("success", "session", "会话已恢复，继续监听轮次")
                await self.state.publish_snapshot()

    async def _wait_until(
        self,
        config: AppConfig,
        scheduled_for: datetime,
        selected: RoundOption,
    ) -> RoundOption:
        self.state.snapshot.automation = AutomationPhase.WAITING
        self.state.snapshot.scheduled_for = scheduled_for
        await self.state.set_scheduler(SchedulerPhase.SCHEDULED)
        next_keepalive = self.now() + timedelta(seconds=config.auth.keepalive_seconds)
        next_round_check = self.now() + timedelta(seconds=2)
        while True:
            current = self.now()
            if current >= next_round_check:
                latest = await self._resolve_round(config)
                if latest.id != selected.id or latest.name != selected.name:
                    previous_name = selected.name
                    selected = latest
                    self.state.snapshot.round_id = selected.id
                    self.state.snapshot.round_name = selected.name
                    await self.state.add_event(
                        "info",
                        "round",
                        f"轮次已变化：{previous_name} -> {selected.name}",
                    )
                next_round_check = current + timedelta(seconds=2)
            remaining = (scheduled_for - current).total_seconds()
            if remaining <= 0:
                break
            self.state.snapshot.countdown_seconds = max(0, math.ceil(remaining))
            await self.state.publish_snapshot()
            if current >= next_keepalive:
                if not await self.auth.check_session():
                    self.state.snapshot.authenticated = False
                    await self._ensure_authenticated(config)
                    self.state.snapshot.automation = AutomationPhase.WAITING
                next_keepalive = self.now() + timedelta(seconds=config.auth.keepalive_seconds)
            await self.sleep(min(1.0, remaining))
        return selected
