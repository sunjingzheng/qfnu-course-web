from __future__ import annotations

import json
import os
from datetime import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError

from .models import CourseTarget, StrictModel


class ConfigError(RuntimeError):
    pass


class AccountConfig(StrictModel):
    username: str = ""


class AuthConfig(StrictModel):
    ocr_url: str | None = None
    ocr_attempts: int = Field(default=3, ge=1, le=10)
    keepalive_seconds: int = Field(default=300, ge=30, le=3600)


class SelectionConfig(StrictModel):
    round_keywords: list[str] = Field(default_factory=list)
    start_time: time | None = None
    requests_per_second: float = Field(default=5.0, ge=0.1, le=5.0)
    poll_interval_seconds: float = Field(default=0.1, ge=0.1, le=300)
    max_runtime_minutes: int | None = Field(default=None, ge=1, le=720)
    term_id: str | None = None


class AppConfig(StrictModel):
    version: Literal[1] = 1
    account: AccountConfig = Field(default_factory=AccountConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    targets: list[CourseTarget] = Field(default_factory=list)


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_or_create(self) -> AppConfig:
        if not self.path.exists():
            config = AppConfig()
            self.save(config)
            return config
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return AppConfig.model_validate(data)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ConfigError(f"无法读取配置文件 {self.path.name}：{exc}") from exc

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2).encode(
            "utf-8"
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(payload)
                stream.write(b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise ConfigError(f"无法保存配置文件 {self.path.name}：{exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
