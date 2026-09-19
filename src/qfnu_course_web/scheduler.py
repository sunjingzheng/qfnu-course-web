from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable

from .client import RateLimitedError, RemoteLoginError, SessionExpiredError
from .courses import ModuleUnavailableError, match_target
from .models import (
    CourseCandidate,
    CourseMatch,
    CourseTarget,
    MatchKind,
    RuntimeConfig,
    SchedulerPhase,
    TaskPhase,
)
from .rounds import RoundOption, RoundSelectionError
from .state import AppState

Reauthenticate = Callable[[], Awaitable[bool]]
ResolveRound = Callable[[], Awaitable[RoundOption]]


class CourseScheduler:
    def __init__(
        self,
        state: AppState,
        catalog: object,
        enrollment: object,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        reauthenticate: Reauthenticate | None = None,
        resolve_round: ResolveRound | None = None,
    ) -> None:
        self.state = state
        self.catalog = catalog
        self.enrollment = enrollment
        self.sleep = sleep
        self.clock = clock
        self.reauthenticate = reauthenticate
        self.resolve_round = resolve_round
        self._task: asyncio.Task[None] | None = None
        self._pause = asyncio.Event()
        self._pause.set()
        self._stop = False

    def set_reauthenticate(self, callback: Reauthenticate | None) -> None:
        self.reauthenticate = callback

    def set_round_resolver(self, callback: ResolveRound | None) -> None:
        self.resolve_round = callback

    async def start(self, config: RuntimeConfig, targets: list[CourseTarget]) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            return self._task
        self._stop = False
        self._pause.set()
        await self.state.configure(config, targets)
        self._task = asyncio.create_task(self._run(config, targets), name="course-scheduler")
        return self._task

    async def pause(self) -> None:
        if self._task and not self._task.done():
            self._pause.clear()
            await self.state.set_scheduler(SchedulerPhase.PAUSED)

    async def resume(self) -> None:
        if self._task and not self._task.done():
            self._pause.set()
            await self.state.set_scheduler(SchedulerPhase.RUNNING)

    async def stop(self) -> None:
        self._stop = True
        self._pause.set()
        if self._task and not self._task.done():
            await self._task

    async def _run(self, config: RuntimeConfig, targets: list[CourseTarget]) -> None:
        await self.state.set_scheduler(SchedulerPhase.RUNNING)
        failures = 0
        reauth_attempts = 0
        pending = {target.id for target in targets if target.enabled}
        try:
            round_id = config.round_id
            recovered_initial_round = False
            if self.resolve_round:
                try:
                    selected = await self.resolve_round()
                except RoundSelectionError:
                    self.state.snapshot.round_id = None
                    self.state.snapshot.round_name = None
                    for pending_target in targets:
                        if pending_target.id in pending:
                            await self.state.set_status(
                                pending_target.id,
                                TaskPhase.WAITING,
                                "轮次列表暂时为空，正在监听",
                            )
                    await self.state.add_event("warning", "round", "轮次列表暂时为空，正在持续监听")
                    selected = await self._wait_for_available_round()
                    if selected is None:
                        await self.state.set_scheduler(SchedulerPhase.STOPPED)
                        return
                    await self.state.add_event(
                        "success", "round", f"轮次已恢复：{selected.name}，继续抢课"
                    )
                    recovered_initial_round = True
                round_id = selected.id
                self.state.snapshot.round_name = selected.name
            elif not round_id:
                rounds = await self.catalog.list_rounds()  # type: ignore[attr-defined]
                if not rounds:
                    raise RuntimeError("没有可用选课轮次")
                round_id = getattr(rounds[0], "id", rounds[0])
            await self.catalog.enter_round(round_id)  # type: ignore[attr-defined]
            self.state.snapshot.round_id = round_id
            entered: set[str] = set()
            skip_round_check_once = recovered_initial_round
            while pending and not self._stop:
                await self._pause.wait()
                round_checked = skip_round_check_once
                skip_round_check_once = False
                for target in sorted(targets, key=lambda item: item.priority):
                    if target.id not in pending or self._stop:
                        continue
                    await self._pause.wait()
                    try:
                        if self.resolve_round and not round_checked:
                            round_checked = True
                            current = await self.resolve_round()
                            if (
                                current.id != round_id
                                or current.name != self.state.snapshot.round_name
                            ):
                                previous_name = self.state.snapshot.round_name or round_id
                                await self.catalog.enter_round(current.id)  # type: ignore[attr-defined]
                                round_id = current.id
                                entered.clear()
                                self.state.snapshot.round_id = current.id
                                self.state.snapshot.round_name = current.name
                                await self.state.publish_snapshot()
                                await self.state.add_event(
                                    "info",
                                    "round",
                                    f"轮次已变化：{previous_name} -> {current.name}",
                                )
                        if target.module not in entered:
                            await self.catalog.enter_module(target.module)  # type: ignore[attr-defined]
                            entered.add(target.module)
                        await self.state.set_status(target.id, TaskPhase.SEARCHING, "正在搜索")
                        candidates = await self.catalog.search(target)  # type: ignore[attr-defined]
                        await self.state.set_candidates(candidates)
                        if target.mode == "advanced":
                            matches = self._advanced_matches(target, candidates)
                            if not matches:
                                await self.state.set_status(
                                    target.id,
                                    TaskPhase.WAITING,
                                    "未找到无冲突、未选且有余量的教学班",
                                )
                                continue
                            completed = False
                            for match in matches:
                                if await self._submit_match(
                                    target, match, config, pending, targets
                                ):
                                    completed = True
                                    break
                            if not completed:
                                await self.state.set_status(
                                    target.id,
                                    TaskPhase.WAITING,
                                    "本轮教学班均未选中，继续重试",
                                )
                            failures = 0
                            reauth_attempts = 0
                            continue
                        match = match_target(target, candidates)
                        if match.kind in (MatchKind.NO_MATCH, MatchKind.BLOCKED):
                            await self.state.set_status(target.id, TaskPhase.WAITING, match.message)
                            continue
                        if match.kind is MatchKind.AMBIGUOUS:
                            await self.state.set_status(target.id, TaskPhase.FAILED, match.message)
                            pending.remove(target.id)
                            continue
                        await self._submit_match(target, match, config, pending, targets)
                        failures = 0
                        reauth_attempts = 0
                    except RoundSelectionError:
                        round_id = None
                        entered.clear()
                        self.state.snapshot.round_id = None
                        self.state.snapshot.round_name = None
                        for pending_target in targets:
                            if pending_target.id in pending:
                                await self.state.set_status(
                                    pending_target.id,
                                    TaskPhase.WAITING,
                                    "轮次列表暂时为空，正在监听",
                                )
                        await self.state.add_event(
                            "warning",
                            "round",
                            "轮次列表暂时为空，已停止旧轮次课程请求并持续监听",
                        )
                        current = await self._wait_for_available_round()
                        if current is None:
                            break
                        await self.catalog.enter_round(current.id)  # type: ignore[attr-defined]
                        round_id = current.id
                        self.state.snapshot.round_id = current.id
                        self.state.snapshot.round_name = current.name
                        await self.state.publish_snapshot()
                        await self.state.add_event(
                            "success", "round", f"轮次已恢复：{current.name}，继续抢课"
                        )
                        skip_round_check_once = True
                    except ModuleUnavailableError as exc:
                        entered.discard(target.module)
                        await self.state.set_status(
                            target.id,
                            TaskPhase.WAITING,
                            f"当前轮次暂未开放{exc.label}，继续检测",
                        )
                        await self.state.add_event(
                            "warning",
                            "round",
                            f"当前轮次暂未开放{exc.label}，保留目标并继续检测",
                        )
                    except RateLimitedError as exc:
                        failures += 1
                        delay = exc.retry_after or min(30 * (2 ** (failures - 1)), 300)
                        self.state.snapshot.backoff_seconds = delay
                        await self.state.add_event(
                            "warning", "network", f"服务端限流，等待 {delay:g} 秒"
                        )
                        await self.sleep(delay)
                        self.state.snapshot.backoff_seconds = 0
                    except SessionExpiredError as exc:
                        reauth_attempts += 1
                        await self.state.add_event("warning", "session", str(exc))
                        recovered = False
                        if self.reauthenticate and reauth_attempts <= 3:
                            try:
                                recovered = await self.reauthenticate()
                            except Exception as recovery_error:
                                await self.state.add_event(
                                    "error", "session", f"重新登录失败：{recovery_error}"
                                )
                        if recovered:
                            await self.catalog.enter_round(round_id)  # type: ignore[attr-defined]
                            entered.clear()
                            await self.state.add_event("success", "session", "会话已恢复，继续抢课")
                            continue
                        self._stop = True
                        break
                    except RemoteLoginError as exc:
                        await self.state.add_event("error", "session", str(exc))
                        self._stop = True
                        break
                    except Exception as exc:
                        failures += 1
                        await self.state.add_event("error", "scheduler", str(exc))
                        if failures >= 5:
                            self._stop = True
                            break
                        await self.sleep(min(2**failures, 30))
                if pending and not self._stop:
                    await self.sleep(config.poll_interval_seconds * random.uniform(0.9, 1.1))
            await self.state.set_scheduler(
                SchedulerPhase.COMPLETE if not pending else SchedulerPhase.STOPPED
            )
        except Exception as exc:
            await self.state.add_event("error", "scheduler", str(exc))
            await self.state.set_scheduler(SchedulerPhase.STOPPED)

    async def _wait_for_available_round(self) -> RoundOption | None:
        if self.resolve_round is None:
            return None
        while not self._stop:
            await self._pause.wait()
            try:
                return await self.resolve_round()
            except RoundSelectionError:
                await self.sleep(1)
        return None

    async def _submit_match(
        self,
        target: CourseTarget,
        match: CourseMatch,
        config: RuntimeConfig,
        pending: set[str],
        targets: list[CourseTarget],
    ) -> bool:
        await self.state.set_status(target.id, TaskPhase.SUBMITTING, "正在提交选课")
        result = await self.enrollment.enroll(match)  # type: ignore[attr-defined]
        if not result.complete:
            await self.state.set_status(target.id, TaskPhase.WAITING, result.message)
            return False
        await self.state.set_status(target.id, TaskPhase.VERIFYING, "正在确认选课结果")
        verified = False
        if config.term_id:
            verified = await self.enrollment.verify(target, config.term_id)  # type: ignore[attr-defined]
        if verified:
            await self.state.set_status(target.id, TaskPhase.SUCCESS, "选课成功并已确认")
            target_label = target.course_name or target.course_code or target.class_id
            await self.state.add_event("success", "enrollment", f"{target_label} 选课成功")
            pending.discard(target.id)
            if target.exclusive_group:
                for other in targets:
                    if other.id in pending and other.exclusive_group == target.exclusive_group:
                        pending.discard(other.id)
                        await self.state.set_status(
                            other.id,
                            TaskPhase.SKIPPED,
                            f"同组课程 {target_label} 已成功",
                        )
            return True
        if not config.term_id:
            await self.state.set_status(
                target.id,
                TaskPhase.SUCCESS,
                "选课请求成功，未配置学期 ID，未二次确认",
            )
            await self.state.add_event(
                "warning",
                "enrollment",
                "选课接口返回成功；未配置学期 ID，无法查询结果列表",
            )
            pending.discard(target.id)
            return True
        await self.state.set_status(
            target.id, TaskPhase.WAITING, "提交成功，但结果列表尚未确认，继续重试"
        )
        return False

    @staticmethod
    def _advanced_matches(
        target: CourseTarget, candidates: list[CourseCandidate]
    ) -> list[CourseMatch]:
        eligible = [
            item
            for item in candidates
            if item.course_code == target.course_code
            and not item.conflict
            and not item.selected
            and item.remaining != 0
        ]
        ordinary = [item for item in eligible if item.split_flag not in (1, 4)]
        matches = [
            CourseMatch(
                kind=MatchKind.ORDINARY,
                target_id=target.id,
                message="课程编号匹配教学班",
                candidate=item,
            )
            for item in ordinary
        ]
        lectures = [item for item in eligible if item.split_flag == 1]
        labs = [item for item in eligible if item.split_flag == 4]
        for lab in labs:
            lecture = next(
                (
                    item
                    for item in lectures
                    if item.course_id == lab.course_id
                    and (not lab.parent_class_id or lab.parent_class_id == item.class_id)
                ),
                None,
            )
            if lecture:
                matches.append(
                    CourseMatch(
                        kind=MatchKind.LECTURE_LAB,
                        target_id=target.id,
                        message="课程编号匹配讲课与实验班",
                        lecture=lecture,
                        lab=lab,
                    )
                )
        return matches
