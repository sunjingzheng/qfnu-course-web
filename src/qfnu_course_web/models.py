from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

ModuleKey = Literal["bxxk", "xxxk", "bxqjhxk", "knjxk", "fawxk", "ggxxkxk"]
TargetMode = Literal["search", "advanced"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuntimeConfig(StrictModel):
    requests_per_second: float = Field(default=5.0, ge=0.1, le=5.0)
    poll_interval_seconds: float = Field(default=0.1, ge=0.1, le=300)
    max_runtime_minutes: int | None = Field(default=None, ge=1, le=720)
    round_id: str | None = None
    term_id: str | None = None
    ocr_url: str | None = None


class CourseTarget(StrictModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    enabled: bool = True
    mode: TargetMode = "search"
    module: ModuleKey
    course_id: str | None = None
    course_code: str | None = None
    course_name: str | None = None
    class_id: str | None = None
    lecture_class_id: str | None = None
    teacher: str | None = None
    lab_group: str | None = None
    weekday: str | None = None
    periods: str | None = None
    exclusive_group: str | None = None
    priority: int = Field(default=100, ge=1, le=9999)

    @model_validator(mode="after")
    def require_identifier(self) -> CourseTarget:
        if self.mode == "advanced":
            if not self.course_code:
                raise ValueError("高级模式必须填写课程编号")
            return self
        if not any((self.course_id, self.course_code, self.course_name, self.class_id)):
            raise ValueError("至少填写课程 ID、课程号、课程名或教学班 ID 中的一项")
        return self


class CourseQuery(StrictModel):
    module: ModuleKey
    course_id: str | None = None
    course_code: str | None = None
    course_name: str | None = None
    teacher: str | None = None
    weekday: str | None = None
    periods: str | None = None


class CourseCandidate(StrictModel):
    catalog_id: str | None = None
    module: ModuleKey
    course_id: str = ""
    course_code: str = ""
    course_name: str = ""
    class_id: str = ""
    teacher: str = ""
    remaining: int | None = None
    enrolled: int | None = None
    capacity: int | None = None
    schedule: str = ""
    location: str = ""
    campus: str = ""
    credits: float | None = None
    department: str = ""
    category: str = ""
    conflict: str = ""
    selected: bool = False
    split_flag: int | None = None
    parent_class_id: str | None = None
    lab_group: str | None = None


class MatchKind(StrEnum):
    NO_MATCH = "no_match"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"
    ORDINARY = "ordinary"
    LECTURE_LAB = "lecture_lab"


class CourseMatch(StrictModel):
    kind: MatchKind
    target_id: str
    message: str
    candidate: CourseCandidate | None = None
    lecture: CourseCandidate | None = None
    lab: CourseCandidate | None = None


class TaskPhase(StrEnum):
    IDLE = "idle"
    WAITING = "waiting"
    SEARCHING = "searching"
    READY = "ready"
    SUBMITTING = "submitting"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"
    SKIPPED = "skipped"


class TargetStatus(StrictModel):
    target_id: str
    phase: TaskPhase = TaskPhase.IDLE
    message: str = "等待启动"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EventLevel(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class Event(StrictModel):
    id: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    level: EventLevel = EventLevel.INFO
    category: str
    message: str


class SchedulerPhase(StrEnum):
    IDLE = "idle"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETE = "complete"


class AutomationPhase(StrEnum):
    IDLE = "idle"
    SIGNING_IN = "signing_in"
    NEEDS_CAPTCHA = "needs_captcha"
    SELECTING_ROUND = "selecting_round"
    WAITING = "waiting"
    RUNNING = "running"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETE = "complete"


class AppSnapshot(StrictModel):
    authenticated: bool = False
    username: str | None = None
    captcha_data_url: str | None = None
    round_id: str | None = None
    round_name: str | None = None
    scheduler: SchedulerPhase = SchedulerPhase.IDLE
    automation: AutomationPhase = AutomationPhase.IDLE
    scheduled_for: datetime | None = None
    countdown_seconds: int = 0
    backoff_seconds: float = 0
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    targets: list[CourseTarget] = Field(default_factory=list)
    statuses: list[TargetStatus] = Field(default_factory=list)
    candidates: list[CourseCandidate] = Field(default_factory=list)
    catalog_candidates: list[CourseCandidate] = Field(default_factory=list)
    catalog_module_counts: dict[str, int] = Field(default_factory=dict)
    catalog_module_errors: dict[str, str] = Field(default_factory=dict)
    catalog_loaded_at: datetime | None = None
    events: list[Event] = Field(default_factory=list)
