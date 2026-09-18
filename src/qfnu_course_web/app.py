from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import yaml
from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field

from .auth import AuthError, AuthService
from .automation import AutomationController, AutomationError
from .catalog import CatalogError, CatalogService
from .client import RateLimitedError, RemoteLoginError, SessionExpiredError, TeachingClient
from .config import AppConfig, ConfigStore
from .courses import CourseCatalog, match_target
from .enrollment import EnrollmentService
from .keychain import KeychainError, KeychainStore
from .models import CourseTarget, RuntimeConfig
from .ocr import BuiltinOcr
from .rate_limit import GlobalRateLimiter
from .scheduler import CourseScheduler
from .state import AppState

PACKAGE_DIR = Path(__file__).parent
PROJECT_DIR = PACKAGE_DIR.parent.parent
FIXED_REQUESTS_PER_SECOND = 5.0
FIXED_POLL_INTERVAL_SECONDS = 0.1


def fixed_selection(selection):
    return selection.model_copy(
        update={
            "round_keywords": [],
            "start_time": None,
            "requests_per_second": FIXED_REQUESTS_PER_SECOND,
            "poll_interval_seconds": FIXED_POLL_INTERVAL_SECONDS,
            "max_runtime_minutes": None,
            "term_id": None,
        }
    )


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    captcha: str


class ConfigDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime: RuntimeConfig
    targets: list[CourseTarget]


class CatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    round_id: str | None = None


class CandidateTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_id: str
    priority: int = Field(default=100, ge=1, le=9999)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str


class AutomationCaptchaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captcha: str


class Services:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        ocr_transport: httpx.AsyncBaseTransport | None = None,
        config_path: Path | None = None,
        keychain: KeychainStore | None = None,
        builtin_ocr: object | None = None,
    ) -> None:
        self.state = AppState()
        self.config_store = ConfigStore(config_path) if config_path is not None else None
        self.config = self.config_store.load_or_create() if self.config_store else AppConfig()
        self.keychain = keychain or KeychainStore()
        self.client = TeachingClient(transport=transport, on_request=self._on_request)
        self.builtin_ocr = builtin_ocr or BuiltinOcr()
        self.auth = AuthService(
            self.client,
            ocr_transport=ocr_transport,
            builtin_ocr=self.builtin_ocr,
        )
        self.catalog = CourseCatalog(self.client)
        self.catalog_browser = CatalogService(self.catalog)
        self.enrollment = EnrollmentService(self.client)
        self.scheduler = CourseScheduler(self.state, self.catalog, self.enrollment)
        self.automation = AutomationController(
            self.state,
            self.auth,
            self.keychain,
            self.catalog,
            self.scheduler,
        )
        self.apply_config(self.config)
        self.save_config()

    def apply_config(self, config: AppConfig) -> None:
        selection = fixed_selection(config.selection)
        auth = config.auth.model_copy(update={"ocr_url": None})
        self.config = config.model_copy(update={"selection": selection, "auth": auth})
        runtime = RuntimeConfig(
            requests_per_second=selection.requests_per_second,
            poll_interval_seconds=selection.poll_interval_seconds,
            max_runtime_minutes=None,
            term_id=selection.term_id,
            ocr_url=None,
        )
        self.state.snapshot.runtime = runtime
        self.state.snapshot.targets = list(config.targets)
        self.client.limiter = GlobalRateLimiter(runtime.requests_per_second)

    async def start(self) -> None:
        await self.auth.start()

    def save_config(self) -> None:
        if self.config_store is not None:
            self.config_store.save(self.config)

    def sync_targets(self) -> None:
        self.config = self.config.model_copy(update={"targets": list(self.state.snapshot.targets)})
        self.save_config()

    async def _on_request(self, method: str, path: str, status: int, duration: float) -> None:
        await self.state.add_event(
            "info", "network", f"{method} {path} -> {status} ({duration * 1000:.0f} ms)"
        )

    async def close(self) -> None:
        await self.automation.stop()
        await self.auth.close()
        self.client.http.cookies.clear()
        await self.client.close()


def create_app(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    ocr_transport: httpx.AsyncBaseTransport | None = None,
    config_path: Path | None = None,
    keychain: KeychainStore | None = None,
    builtin_ocr: object | None = None,
) -> FastAPI:
    services = Services(
        transport=transport,
        ocr_transport=ocr_transport,
        config_path=config_path,
        keychain=keychain,
        builtin_ocr=builtin_ocr,
    )
    token = secrets.token_urlsafe(32)
    templates = Environment(
        loader=FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=select_autoescape(("html", "xml")),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await services.start()
        yield
        await services.close()

    app = FastAPI(title="QFNU 选课控制台", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.services = services
    app.state.session_token = token
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        origin = request.headers.get("origin")
        if (
            origin
            and origin not in {"http://127.0.0.1", "http://localhost"}
            and not origin.startswith(("http://127.0.0.1:", "http://localhost:"))
        ):
            return PlainTextResponse("Forbidden", status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def require_token(x_qfnu_token: str | None = Header(default=None)) -> None:
        if not x_qfnu_token or not secrets.compare_digest(x_qfnu_token, token):
            raise HTTPException(status_code=403, detail="无效的本地会话令牌")

    def require_login() -> None:
        if not services.state.snapshot.authenticated:
            raise HTTPException(status_code=409, detail="请先登录")

    async def resolve_round_id(requested: str | None = None) -> str:
        if requested:
            return requested
        rounds = await services.catalog.list_rounds()
        if not rounds:
            raise HTTPException(status_code=409, detail="没有可用选课轮次")
        return rounds[0].id

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return templates.get_template("index.html").render(token=token)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/state")
    async def get_state() -> dict[str, object]:
        return services.state.snapshot.model_dump(mode="json")

    def automation_config_payload() -> dict[str, object]:
        payload = services.config.model_dump(mode="json")
        username = services.config.account.username
        payload["password_saved"] = bool(username) and services.keychain.has(username)
        return payload

    @app.get("/api/automation/config")
    async def get_automation_config(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        return automation_config_payload()

    @app.put("/api/automation/config")
    async def update_automation_config(
        payload: AppConfig, x_qfnu_token: str | None = Header(default=None)
    ):
        require_token(x_qfnu_token)
        services.apply_config(payload)
        services.save_config()
        await services.state.configure(
            services.state.snapshot.runtime, services.state.snapshot.targets
        )
        return automation_config_payload()

    @app.put("/api/automation/password")
    async def save_automation_password(
        payload: PasswordInput, x_qfnu_token: str | None = Header(default=None)
    ):
        require_token(x_qfnu_token)
        try:
            services.keychain.save(services.config.account.username, payload.password)
        except KeychainError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"password_saved": True}

    @app.delete("/api/automation/password")
    async def delete_automation_password(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        try:
            services.keychain.delete(services.config.account.username)
        except KeychainError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"password_saved": False}

    @app.post("/api/automation/start")
    async def start_automation(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        try:
            await services.automation.start(services.config)
        except AutomationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/automation/captcha")
    async def submit_automation_captcha(
        payload: AutomationCaptchaInput,
        x_qfnu_token: str | None = Header(default=None),
    ):
        require_token(x_qfnu_token)
        try:
            await services.automation.submit_captcha(payload.captcha)
        except AutomationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/auth/captcha")
    async def captcha(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        try:
            data_url = await services.auth.begin_login()
        except (AuthError, httpx.HTTPError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        services.state.snapshot.captcha_data_url = data_url
        await services.state.publish_snapshot()
        return {"captcha_data_url": data_url}

    @app.post("/api/auth/login")
    async def login(payload: LoginInput, x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        try:
            result = await services.auth.complete_login(
                payload.username, payload.password, payload.captcha
            )
        except (AuthError, httpx.HTTPError) as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        services.state.snapshot.authenticated = result.authenticated
        services.state.snapshot.username = result.username
        services.state.snapshot.captcha_data_url = None
        await services.state.add_event("success", "auth", "登录成功")
        await services.state.publish_snapshot()
        return {"authenticated": True, "username": result.username}

    @app.post("/api/auth/logout")
    async def logout(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        await services.scheduler.stop()
        services.client.http.cookies.clear()
        services.state.snapshot.authenticated = False
        services.state.snapshot.username = None
        services.state.snapshot.captcha_data_url = None
        services.state.snapshot.round_id = None
        services.catalog_browser.clear()
        await services.state.set_catalog([])
        await services.state.set_candidates([])
        await services.state.add_event("info", "auth", "已退出并清除会话")
        await services.state.publish_snapshot()
        return {"ok": True}

    @app.put("/api/runtime")
    async def update_runtime(
        payload: RuntimeConfig, x_qfnu_token: str | None = Header(default=None)
    ):
        require_token(x_qfnu_token)
        runtime = payload.model_copy(
            update={
                "requests_per_second": FIXED_REQUESTS_PER_SECOND,
                "poll_interval_seconds": FIXED_POLL_INTERVAL_SECONDS,
                "max_runtime_minutes": None,
                "term_id": None,
            }
        )
        services.state.snapshot.runtime = runtime
        services.client.limiter = GlobalRateLimiter(FIXED_REQUESTS_PER_SECOND)
        services.config = services.config.model_copy(
            update={
                "selection": fixed_selection(services.config.selection),
                "auth": services.config.auth.model_copy(update={"ocr_url": None}),
            }
        )
        services.save_config()
        await services.state.publish_snapshot()
        return runtime.model_dump(mode="json")

    @app.post("/api/targets")
    async def create_target(payload: CourseTarget, x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        services.state.snapshot.targets.append(payload)
        await services.state.configure(
            services.state.snapshot.runtime, services.state.snapshot.targets
        )
        services.sync_targets()
        return payload.model_dump(mode="json")

    @app.get("/api/rounds")
    async def list_rounds(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        require_login()
        try:
            rounds = await services.catalog.list_rounds()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="无法获取选课轮次") from exc
        return {"rounds": [item.as_dict() for item in rounds]}

    @app.post("/api/courses/catalog")
    async def load_catalog(payload: CatalogInput, x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        require_login()
        try:
            round_id = await resolve_round_id(payload.round_id)
            result = await services.catalog_browser.load(round_id)
        except RateLimitedError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except (RemoteLoginError, SessionExpiredError) as exc:
            services.state.snapshot.authenticated = False
            await services.state.publish_snapshot()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="无法加载课程目录") from exc
        services.state.snapshot.round_id = round_id
        services.state.snapshot.runtime.round_id = round_id
        await services.state.set_catalog(
            result.candidates,
            result.module_counts,
            result.module_errors,
            result.loaded_at,
        )
        await services.state.add_event(
            "success", "catalog", f"已加载 {len(result.candidates)} 条课程记录"
        )
        return {
            "round_id": round_id,
            "candidates": [item.model_dump(mode="json") for item in result.candidates],
            "module_counts": result.module_counts,
            "module_errors": result.module_errors,
            "loaded_at": result.loaded_at.isoformat(),
        }

    @app.post("/api/targets/from-candidate")
    async def create_target_from_candidate(
        payload: CandidateTargetInput, x_qfnu_token: str | None = Header(default=None)
    ):
        require_token(x_qfnu_token)
        require_login()
        try:
            target = services.catalog_browser.target_from_candidate(
                payload.catalog_id, payload.priority, services.state.snapshot.targets
            )
        except CatalogError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        services.state.snapshot.targets.append(target)
        await services.state.configure(
            services.state.snapshot.runtime, services.state.snapshot.targets
        )
        services.sync_targets()
        return target.model_dump(mode="json")

    @app.put("/api/targets/{target_id}")
    async def update_target(
        target_id: str, payload: CourseTarget, x_qfnu_token: str | None = Header(default=None)
    ):
        require_token(x_qfnu_token)
        targets = services.state.snapshot.targets
        for index, target in enumerate(targets):
            if target.id == target_id:
                payload.id = target_id
                targets[index] = payload
                await services.state.configure(services.state.snapshot.runtime, targets)
                services.sync_targets()
                return payload.model_dump(mode="json")
        raise HTTPException(status_code=404, detail="目标课程不存在")

    @app.delete("/api/targets/{target_id}")
    async def delete_target(target_id: str, x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        targets = [item for item in services.state.snapshot.targets if item.id != target_id]
        if len(targets) == len(services.state.snapshot.targets):
            raise HTTPException(status_code=404, detail="目标课程不存在")
        await services.state.configure(services.state.snapshot.runtime, targets)
        services.sync_targets()
        return {"ok": True}

    @app.post("/api/config/import")
    async def import_config(
        body: str = Body(media_type="text/plain"), x_qfnu_token: str | None = Header(default=None)
    ):
        require_token(x_qfnu_token)
        try:
            data = yaml.safe_load(body)
            document = ConfigDocument.model_validate(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"配置无效：{exc}") from exc
        runtime = document.runtime.model_copy(
            update={
                "requests_per_second": FIXED_REQUESTS_PER_SECOND,
                "poll_interval_seconds": FIXED_POLL_INTERVAL_SECONDS,
                "max_runtime_minutes": None,
                "term_id": None,
            }
        )
        services.client.limiter = GlobalRateLimiter(FIXED_REQUESTS_PER_SECOND)
        await services.state.configure(runtime, document.targets)
        services.config = services.config.model_copy(
            update={
                "selection": fixed_selection(services.config.selection),
                "auth": services.config.auth.model_copy(update={"ocr_url": None}),
                "targets": list(document.targets),
            }
        )
        services.save_config()
        return {
            "runtime": runtime.model_dump(mode="json"),
            "targets": document.model_dump(mode="json")["targets"],
        }

    @app.get("/api/config/export", response_class=PlainTextResponse)
    async def export_config() -> str:
        data = {
            "runtime": services.state.snapshot.runtime.model_dump(mode="json"),
            "targets": [item.model_dump(mode="json") for item in services.state.snapshot.targets],
        }
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    @app.post("/api/scheduler/start")
    async def start_scheduler(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        if not services.state.snapshot.authenticated:
            raise HTTPException(status_code=409, detail="请先登录")
        if not services.state.snapshot.targets:
            raise HTTPException(status_code=409, detail="请先添加目标课程")
        await services.scheduler.start(
            services.state.snapshot.runtime, services.state.snapshot.targets
        )
        return {"ok": True}

    @app.post("/api/scheduler/pause")
    async def pause_scheduler(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        await services.scheduler.pause()
        return {"ok": True}

    @app.post("/api/scheduler/resume")
    async def resume_scheduler(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        await services.scheduler.resume()
        return {"ok": True}

    @app.post("/api/scheduler/stop")
    async def stop_scheduler(x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        await services.automation.stop()
        return {"ok": True}

    @app.post("/api/targets/{target_id}/refresh")
    async def refresh_target(target_id: str, x_qfnu_token: str | None = Header(default=None)):
        require_token(x_qfnu_token)
        if not services.state.snapshot.authenticated:
            raise HTTPException(status_code=409, detail="请先登录")
        target = next(
            (item for item in services.state.snapshot.targets if item.id == target_id), None
        )
        if target is None:
            raise HTTPException(status_code=404, detail="目标课程不存在")
        round_id = services.state.snapshot.runtime.round_id
        if not round_id:
            rounds = await services.catalog.list_rounds()
            if not rounds:
                raise HTTPException(status_code=409, detail="没有可用选课轮次")
            round_id = rounds[0].id
        await services.catalog.enter_round(round_id)
        services.state.snapshot.round_id = round_id
        await services.catalog.enter_module(target.module)
        rows = await services.catalog.search(target)
        return {
            "match": match_target(target, rows).model_dump(mode="json"),
            "candidates": [row.model_dump(mode="json") for row in rows],
        }

    @app.get("/api/events")
    async def events():
        queue = await services.state.subscribe()

        async def stream():
            try:
                while True:
                    try:
                        kind, data = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    except TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                await services.state.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


app = create_app(config_path=PROJECT_DIR / "config.json")
