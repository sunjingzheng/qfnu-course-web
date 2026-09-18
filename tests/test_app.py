import re
from pathlib import Path

import httpx
import pytest

from qfnu_course_web.app import create_app
from qfnu_course_web.models import CourseCandidate


class NoWaitLimiter:
    async def acquire(self) -> None:
        return None


class FakeKeychain:
    def __init__(self) -> None:
        self.passwords: dict[str, str] = {}

    def save(self, username: str, password: str) -> None:
        self.passwords[username] = password

    def read(self, username: str) -> str:
        return self.passwords[username]

    def has(self, username: str) -> bool:
        return username in self.passwords

    def delete(self, username: str) -> bool:
        return self.passwords.pop(username, None) is not None


async def api_client(app):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
    page = await client.get("/")
    token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
    return client, {"X-QFNU-Token": token}


@pytest.mark.asyncio
async def test_automation_config_is_persisted_without_a_password(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    keychain = FakeKeychain()
    app = create_app(config_path=config_path, keychain=keychain)
    client, headers = await api_client(app)
    try:
        payload = {
            "version": 1,
            "account": {"username": "2024000000"},
            "auth": {
                "ocr_url": "http://ocr.local",
                "ocr_attempts": 3,
                "keepalive_seconds": 60,
            },
            "selection": {
                "round_keywords": ["补选", "正选"],
                "start_time": "10:00:00",
                "requests_per_second": 2,
                "poll_interval_seconds": 3,
                "max_runtime_minutes": 60,
                "term_id": "term-1",
            },
            "targets": [{"module": "xxxk", "course_code": "001"}],
        }
        response = await client.put("/api/automation/config", headers=headers, json=payload)
        loaded = await client.get("/api/automation/config", headers=headers)
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert loaded.json()["account"]["username"] == "2024000000"
    assert loaded.json()["password_saved"] is False
    assert "password" not in loaded.json()
    assert "password" not in config_path.read_text(encoding="utf-8").lower()
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert app.state.services.state.snapshot.targets[0].course_code == "001"
    selection = loaded.json()["selection"]
    assert selection == {
        "round_keywords": [],
        "start_time": None,
        "requests_per_second": 5.0,
        "poll_interval_seconds": 0.1,
        "max_runtime_minutes": None,
        "term_id": None,
    }
    runtime = app.state.services.state.snapshot.runtime
    assert runtime.requests_per_second == 5.0
    assert runtime.poll_interval_seconds == 0.1
    assert runtime.max_runtime_minutes is None
    assert runtime.term_id is None


@pytest.mark.asyncio
async def test_legacy_runtime_api_cannot_override_fixed_parameters(tmp_path: Path) -> None:
    app = create_app(config_path=tmp_path / "config.json", keychain=FakeKeychain())
    client, headers = await api_client(app)
    try:
        response = await client.put(
            "/api/runtime",
            headers=headers,
            json={
                "requests_per_second": 0.1,
                "poll_interval_seconds": 300,
                "max_runtime_minutes": 1,
                "term_id": "legacy-term",
                "ocr_url": "http://ocr.local",
            },
        )
        loaded = await client.get("/api/automation/config", headers=headers)
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert response.json()["requests_per_second"] == 5.0
    assert response.json()["poll_interval_seconds"] == 0.1
    assert response.json()["max_runtime_minutes"] is None
    assert response.json()["term_id"] is None
    assert loaded.json()["selection"] == {
        "round_keywords": [],
        "start_time": None,
        "requests_per_second": 5.0,
        "poll_interval_seconds": 0.1,
        "max_runtime_minutes": None,
        "term_id": None,
    }


@pytest.mark.asyncio
async def test_password_save_and_delete_only_report_status(tmp_path: Path) -> None:
    keychain = FakeKeychain()
    app = create_app(config_path=tmp_path / "config.json", keychain=keychain)
    client, headers = await api_client(app)
    try:
        await client.put(
            "/api/automation/config",
            headers=headers,
            json={"account": {"username": "2024000000"}},
        )
        saved = await client.put(
            "/api/automation/password", headers=headers, json={"password": "secret-value"}
        )
        loaded = await client.get("/api/automation/config", headers=headers)
        deleted = await client.delete("/api/automation/password", headers=headers)
    finally:
        await client.aclose()

    assert saved.json() == {"password_saved": True}
    assert loaded.json()["password_saved"] is True
    assert "secret-value" not in saved.text + loaded.text + deleted.text
    assert deleted.json() == {"password_saved": False}


@pytest.mark.asyncio
async def test_automation_start_and_manual_captcha_routes(tmp_path: Path) -> None:
    class FakeAutomation:
        def __init__(self) -> None:
            self.started = None
            self.captcha = None

        async def start(self, config):
            self.started = config

        async def submit_captcha(self, captcha):
            self.captcha = captcha

    app = create_app(config_path=tmp_path / "config.json", keychain=FakeKeychain())
    fake = FakeAutomation()
    app.state.services.automation = fake
    client, headers = await api_client(app)
    try:
        await client.put(
            "/api/automation/config",
            headers=headers,
            json={
                "account": {"username": "2024000000"},
                "selection": {"term_id": "term-1"},
                "targets": [{"module": "xxxk", "course_code": "001"}],
            },
        )
        started = await client.post("/api/automation/start", headers=headers)
        captcha = await client.post(
            "/api/automation/captcha", headers=headers, json={"captcha": "abcd"}
        )
    finally:
        await client.aclose()

    assert started.status_code == 200
    assert fake.started.account.username == "2024000000"
    assert captcha.status_code == 200
    assert fake.captcha == "abcd"


@pytest.mark.asyncio
async def test_local_api_requires_session_token_for_writes() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        assert page.status_code == 200
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        assert (await client.get("/api/state")).status_code == 200
        assert (await client.post("/api/scheduler/start")).status_code == 403
        response = await client.post(
            "/api/targets",
            headers={"X-QFNU-Token": token},
            json={"module": "xxxk", "course_code": "001"},
        )
        assert response.status_code == 200
        state = (await client.get("/api/state")).json()
        assert state["targets"][0]["course_code"] == "001"


@pytest.mark.asyncio
async def test_foreign_origin_is_rejected() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        response = await client.post(
            "/api/targets",
            headers={"X-QFNU-Token": token, "Origin": "https://evil.example"},
            json={"module": "xxxk", "course_code": "001"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_scheduler_start_allows_missing_term_id() -> None:
    class RecordingScheduler:
        def __init__(self) -> None:
            self.started = False

        async def start(self, runtime, targets):
            self.started = True

    app = create_app()
    scheduler = RecordingScheduler()
    app.state.services.scheduler = scheduler
    app.state.services.state.snapshot.authenticated = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        headers = {"X-QFNU-Token": token}
        await client.post(
            "/api/targets",
            headers=headers,
            json={"module": "xxxk", "course_code": "001"},
        )

        response = await client.post("/api/scheduler/start", headers=headers)

        assert response.status_code == 200
        assert scheduler.started is True


@pytest.mark.asyncio
async def test_target_refresh_enters_round_and_module_before_search() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/jsxsd/xsxk/xklc_list":
            return httpx.Response(200, text='<a href="xsxk_index?jx0502zbid=round-1">进入</a>')
        if request.url.path == "/jsxsd/xsxkkc/xsxkXxxk":
            return httpx.Response(200, json={"aaData": []})
        return httpx.Response(200, text="ok")

    app = create_app(transport=httpx.MockTransport(handler))
    app.state.services.state.snapshot.authenticated = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        headers = {"X-QFNU-Token": token}
        target = (
            await client.post(
                "/api/targets",
                headers=headers,
                json={"module": "xxxk", "course_code": "001"},
            )
        ).json()

        response = await client.post(f"/api/targets/{target['id']}/refresh", headers=headers)

        assert response.status_code == 200
        assert requests == [
            ("GET", "/jsxsd/xsxk/xklc_list"),
            ("GET", "/jsxsd/xsxk/xsxk_index"),
            ("GET", "/jsxsd/xsxkkc/comeInXxxk"),
            ("POST", "/jsxsd/xsxkkc/xsxkXxxk"),
        ]
        assert app.state.services.state.snapshot.round_id == "round-1"


@pytest.mark.asyncio
async def test_target_refresh_requires_login() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        headers = {"X-QFNU-Token": token}
        target = (
            await client.post(
                "/api/targets",
                headers=headers,
                json={"module": "xxxk", "course_code": "001"},
            )
        ).json()

        response = await client.post(f"/api/targets/{target['id']}/refresh", headers=headers)

        assert response.status_code == 409
        assert response.json()["detail"] == "请先登录"


@pytest.mark.asyncio
async def test_rounds_and_catalog_require_login() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        headers = {"X-QFNU-Token": token}

        assert (await client.get("/api/rounds", headers=headers)).status_code == 409
        assert (
            await client.post("/api/courses/catalog", headers=headers, json={"round_id": "round-1"})
        ).status_code == 409


@pytest.mark.asyncio
async def test_catalog_loads_all_modules_and_adds_a_cached_candidate() -> None:
    search_paths = {
        "/jsxsd/xsxkkc/xsxkBxxk": "bxxk",
        "/jsxsd/xsxkkc/xsxkXxxk": "xxxk",
        "/jsxsd/xsxkkc/xsxkBxqjhxk": "bxqjhxk",
        "/jsxsd/xsxkkc/xsxkKnjxk": "knjxk",
        "/jsxsd/xsxkkc/xsxkFawxk": "fawxk",
        "/jsxsd/xsxkkc/xsxkGgxxkxk": "ggxxkxk",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jsxsd/xsxk/xklc_list":
            return httpx.Response(200, text="jrxk('round-1')")
        module = search_paths.get(request.url.path)
        if module:
            return httpx.Response(
                200,
                json={
                    "aaData": [
                        {
                            "jx02id": f"course-{module}",
                            "jx0404id": f"class-{module}",
                            "kch": f"code-{module}",
                            "kcmc": f"课程 {module}",
                            "skls": "张老师",
                            "xf": "2",
                            "dwmc": "测试学院",
                        }
                    ]
                },
            )
        return httpx.Response(200, text="ok")

    app = create_app(transport=httpx.MockTransport(handler))
    app.state.services.client.limiter = NoWaitLimiter()
    app.state.services.state.snapshot.authenticated = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        headers = {"X-QFNU-Token": token}

        rounds = await client.get("/api/rounds", headers=headers)
        catalog = await client.post(
            "/api/courses/catalog", headers=headers, json={"round_id": "round-1"}
        )

        assert rounds.json() == {"rounds": [{"id": "round-1", "name": "round-1"}]}
        assert catalog.status_code == 200
        payload = catalog.json()
        assert len(payload["candidates"]) == 6
        assert payload["module_errors"] == {}
        assert len(app.state.services.state.snapshot.catalog_candidates) == 6
        assert app.state.services.state.snapshot.runtime.round_id == "round-1"
        candidate = payload["candidates"][0]
        response = await client.post(
            "/api/targets/from-candidate",
            headers=headers,
            json={"catalog_id": candidate["catalog_id"], "priority": 12},
        )

        assert response.status_code == 200
        assert response.json()["class_id"].startswith("class-")
        duplicate = await client.post(
            "/api/targets/from-candidate",
            headers=headers,
            json={"catalog_id": candidate["catalog_id"], "priority": 12},
        )
        assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_logout_invalidates_the_loaded_catalog() -> None:
    app = create_app()
    app.state.services.state.snapshot.authenticated = True
    app.state.services.catalog_browser.replace(
        [
            CourseCandidate(
                catalog_id="old",
                module="xxxk",
                course_id="course-1",
                class_id="class-1",
                course_name="大学语文",
            )
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        page = await client.get("/")
        token = re.search(r'name="qfnu-token" content="([^"]+)"', page.text).group(1)
        headers = {"X-QFNU-Token": token}
        await client.post("/api/auth/logout", headers=headers)
        app.state.services.state.snapshot.authenticated = True

        response = await client.post(
            "/api/targets/from-candidate",
            headers=headers,
            json={"catalog_id": "old", "priority": 100},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "课程目录记录已失效，请重新加载"
