from __future__ import annotations

import subprocess
from collections.abc import Callable

SERVICE_NAME = "qfnu-course-web"
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class KeychainError(RuntimeError):
    pass


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


class KeychainStore:
    def __init__(self, *, service: str = SERVICE_NAME, runner: Runner = _run) -> None:
        self.service = service
        self.runner = runner

    def save(self, username: str, password: str) -> None:
        username = username.strip()
        if not username:
            raise KeychainError("请先填写学号")
        if not password:
            raise KeychainError("密码不能为空")
        result = self.runner(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self.service,
                "-a",
                username,
                "-w",
                password,
            ]
        )
        if result.returncode != 0:
            raise KeychainError("无法将密码保存到 macOS 钥匙串")

    def read(self, username: str) -> str:
        username = username.strip()
        if not username:
            raise KeychainError("请先填写学号")
        result = self.runner(
            [
                "security",
                "find-generic-password",
                "-s",
                self.service,
                "-a",
                username,
                "-w",
            ]
        )
        if result.returncode != 0:
            raise KeychainError("钥匙串中没有保存密码")
        password = result.stdout.rstrip("\r\n")
        if not password:
            raise KeychainError("钥匙串中的密码为空")
        return password

    def has(self, username: str) -> bool:
        username = username.strip()
        if not username:
            return False
        result = self.runner(
            [
                "security",
                "find-generic-password",
                "-s",
                self.service,
                "-a",
                username,
            ]
        )
        return result.returncode == 0

    def delete(self, username: str) -> bool:
        username = username.strip()
        if not username:
            raise KeychainError("请先填写学号")
        result = self.runner(
            [
                "security",
                "delete-generic-password",
                "-s",
                self.service,
                "-a",
                username,
            ]
        )
        return result.returncode == 0
