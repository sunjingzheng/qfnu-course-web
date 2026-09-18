from subprocess import CompletedProcess

import pytest

from qfnu_course_web.keychain import KeychainError, KeychainStore


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.password: str | None = None

    def __call__(self, command: list[str]) -> CompletedProcess[str]:
        self.calls.append(command)
        action = command[1]
        if action == "add-generic-password":
            self.password = command[-1]
            return CompletedProcess(command, 0, "", "")
        if action == "find-generic-password" and self.password is not None:
            return CompletedProcess(command, 0, f"{self.password}\n", "")
        if action == "delete-generic-password" and self.password is not None:
            self.password = None
            return CompletedProcess(command, 0, "", "")
        return CompletedProcess(command, 44, "", "The specified item could not be found")


def test_keychain_saves_reads_and_deletes_password() -> None:
    runner = FakeRunner()
    store = KeychainStore(runner=runner)

    store.save("2024000000", "secret")

    assert store.read("2024000000") == "secret"
    assert store.has("2024000000") is True
    assert runner.calls[-1][-1] == "2024000000"
    assert "-w" not in runner.calls[-1]
    assert store.delete("2024000000") is True
    assert store.has("2024000000") is False
    assert all(call[0] == "security" for call in runner.calls)


def test_keychain_rejects_blank_values_and_maps_command_errors() -> None:
    store = KeychainStore(runner=FakeRunner())
    with pytest.raises(KeychainError, match="学号"):
        store.save("", "secret")
    with pytest.raises(KeychainError, match="密码"):
        store.save("2024000000", "")
    with pytest.raises(KeychainError, match="没有保存密码"):
        store.read("2024000000")
