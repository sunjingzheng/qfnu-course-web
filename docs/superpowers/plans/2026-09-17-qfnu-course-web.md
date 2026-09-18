# QFNU Course Web Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a localhost Web console that logs into the documented QFNU teaching system, monitors configured courses at no more than two requests per second, enrolls an unambiguous eligible candidate, and verifies the result.

**Architecture:** A FastAPI process owns one in-memory application state and one `httpx.AsyncClient`. Focused domain modules handle configuration, authentication, course parsing and matching, enrollment, scheduling, and event redaction; Jinja HTML plus native JavaScript renders the state and consumes an SSE stream. All network behavior is tested through `httpx.MockTransport`, and no test contacts the live teaching system.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, HTTPX, Pydantic, PyYAML, Beautiful Soup, Jinja2, pytest, pytest-asyncio, native JavaScript and CSS.

---

The directory is not currently a Git repository. The usual commit checkpoints are represented as verification checkpoints; do not initialize Git without the user's request.

## File Map

- `pyproject.toml`: package metadata, runtime dependencies, pytest and Ruff configuration.
- `README.md`: installation, local startup, safe credential handling, configuration and module coverage.
- `courses.example.yaml`: importable target configuration without credentials.
- `src/qfnu_course_web/models.py`: validated configuration, candidate, task and event models.
- `src/qfnu_course_web/modules.py`: the six documented module endpoint mappings.
- `src/qfnu_course_web/rate_limit.py`: global monotonic request limiter capped at two requests per second.
- `src/qfnu_course_web/client.py`: HTTP session, redirection rules, response checks and redacted events.
- `src/qfnu_course_web/auth.py`: captcha and encoded-login flow.
- `src/qfnu_course_web/courses.py`: round discovery, course search, parsing and deterministic matching.
- `src/qfnu_course_web/enrollment.py`: ordinary and lecture-plus-lab request construction and result verification.
- `src/qfnu_course_web/scheduler.py`: one background task, pause/resume, retries and stopping conditions.
- `src/qfnu_course_web/state.py`: process-local state, event history and SSE subscriptions.
- `src/qfnu_course_web/app.py`: FastAPI routes, CSRF-style local session token and lifecycle cleanup.
- `src/qfnu_course_web/__main__.py`: bind to localhost and open the browser.
- `src/qfnu_course_web/templates/index.html`: the complete console shell and accessible dialogs.
- `src/qfnu_course_web/static/app.js`: state rendering, forms, controls and SSE reconnection.
- `src/qfnu_course_web/static/styles.css`: responsive work-focused visual system.
- `tests/`: unit and route tests described below.

### Task 1: Package Skeleton and Validated Models

**Files:**
- Create: `pyproject.toml`
- Create: `src/qfnu_course_web/__init__.py`
- Create: `src/qfnu_course_web/models.py`
- Create: `src/qfnu_course_web/modules.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Cover all six module keys and assert `RuntimeConfig(requests_per_second=2)` is accepted while `2.01` is rejected. Assert a target must contain at least one of `course_id`, `course_code`, `course_name`, or `class_id` and that unknown YAML fields fail validation.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_models.py -q` and expect collection to fail because `qfnu_course_web.models` does not exist.

- [ ] **Step 3: Implement models and module mappings**

Define strict Pydantic models `RuntimeConfig`, `CourseTarget`, `CourseCandidate`, `TaskStatus`, `AppSnapshot`, and `Event`. Define immutable `ModuleSpec` values for `bxxk`, `xxxk`, `bxqjhxk`, `knjxk`, `fawxk`, and `ggxxkxk` with the exact endpoints from the API document.

- [ ] **Step 4: Verify green**

Run `python3 -m pytest tests/test_models.py -q` and expect all model tests to pass.

### Task 2: Global Limiter and HTTP Safety Boundary

**Files:**
- Create: `src/qfnu_course_web/rate_limit.py`
- Create: `src/qfnu_course_web/client.py`
- Create: `tests/test_rate_limit.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write failing limiter and redirect tests**

Use an injected monotonic clock and sleeper to prove requests are spaced by at least `1 / requests_per_second`. Test same-origin redirects are accepted only during login, cross-origin redirects raise `UnsafeRedirectError`, `429` exposes `Retry-After`, login-page replacement raises `SessionExpiredError`, and the remote-login text raises `RemoteLoginError`.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_rate_limit.py tests/test_client.py -q`; expect import failures for the missing modules.

- [ ] **Step 3: Implement the boundary**

Create `GlobalRateLimiter.acquire()` around an `asyncio.Lock` and `time.monotonic`. Create `TeachingClient.request()` that always acquires the limiter, uses a fixed desktop User-Agent, sets finite connect/read/write timeouts, never follows redirects by default, checks response size, classifies session errors, and emits only method, path, status and timing through an event callback.

- [ ] **Step 4: Verify green**

Run `python3 -m pytest tests/test_rate_limit.py tests/test_client.py -q`; expect all tests to pass.

### Task 3: Authentication Flow

**Files:**
- Create: `src/qfnu_course_web/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing authentication tests**

Assert `encode_credentials("u", "p", "ABC123", "201") == "uAB%C%p"`. With `httpx.MockTransport`, test initialization, captcha retrieval, `scode#sxh` parsing, empty `userAccount` and `userPassword`, `RANDOMCODE`, encoded credentials, same-origin SSO handoff, success-page verification, captcha error, password error, malformed session seed and cross-origin redirect rejection.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_auth.py -q`; expect an import failure for `qfnu_course_web.auth`.

- [ ] **Step 3: Implement authentication**

Implement `AuthService.begin_login()` returning an in-memory data URL for the captcha and `AuthService.complete_login(username, password, captcha)` performing the remaining steps. Clear password references in a `finally` block and return a typed result without credentials.

- [ ] **Step 4: Verify green**

Run `python3 -m pytest tests/test_auth.py -q`; expect all authentication tests to pass.

### Task 4: Search, Parsing and Deterministic Matching

**Files:**
- Create: `src/qfnu_course_web/courses.py`
- Create: `tests/test_courses.py`

- [ ] **Step 1: Write failing search and matching tests**

Test round IDs parsed from `xsxk_index`, entry into each module, POST search parameters including `iDisplayLength=10000`, normal course rows, HTML line breaks, no-result responses, zero remaining places, conflict messages, exact class ID matching, ambiguous name matches, teacher filters, and lecture-plus-lab pairing by equal `jx02id` plus requested `fzmc`.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_courses.py -q`; expect an import failure for `qfnu_course_web.courses`.

- [ ] **Step 3: Implement catalog and matcher**

Implement `CourseCatalog.list_rounds()`, `enter_round()`, `enter_module()`, and `search()`. Normalize string and integer response fields without inventing missing capacity data. Implement `match_target()` returning `NO_MATCH`, `BLOCKED`, `AMBIGUOUS`, `ORDINARY`, or `LECTURE_LAB` plus the exact selected rows.

- [ ] **Step 4: Verify green**

Run `python3 -m pytest tests/test_courses.py -q`; expect all course tests to pass.

### Task 5: Enrollment and Result Verification

**Files:**
- Create: `src/qfnu_course_web/enrollment.py`
- Create: `tests/test_enrollment.py`

- [ ] **Step 1: Write failing enrollment tests**

Assert ordinary enrollment sends only `kcid`, `jx0404id` and `_`. Assert a split course sends `cfbs=4`, `yxcfbs=1`, lecture `yxjx0404id`, `cfmyz=1`, lab `jx0404id`, empty `xkzy` and empty `trjf`. Test that only message `选课成功` is complete, `还有[实验学时]需要选` is incomplete, business failures preserve the server message, and result-table parsing confirms course name or code.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_enrollment.py -q`; expect an import failure for `qfnu_course_web.enrollment`.

- [ ] **Step 3: Implement submission and verification**

Implement `EnrollmentService.enroll(match)` using the selected module's operation endpoint and `verify(target, term_id)` using `/jsxsd/xkgl/xsxkjgcx` plus `/jsxsd/xkgl/loadXsxkjgList`. Parse the HTML table with Beautiful Soup and return typed outcomes.

- [ ] **Step 4: Verify green**

Run `python3 -m pytest tests/test_enrollment.py -q`; expect all enrollment tests to pass.

### Task 6: State Store and Single Scheduler

**Files:**
- Create: `src/qfnu_course_web/state.py`
- Create: `src/qfnu_course_web/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing scheduler tests**

Using fake catalog and enrollment services, assert repeated `start()` creates one task, pause prevents another request after the current request completes, a unique eligible candidate is enrolled and verified once, success produces no later requests, ambiguous and blocked matches never submit, `429` respects `Retry-After`, five consecutive transient failures stop the run, remote login stops immediately, maximum duration stops the run, and a new SSE subscriber receives a complete snapshot before later events.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_scheduler.py -q`; expect import failures for the missing modules.

- [ ] **Step 3: Implement state and scheduler**

Create `AppState` with a lock, bounded 500-event history, snapshot serialization and per-subscriber queues. Create `CourseScheduler` with explicit `IDLE`, `RUNNING`, `PAUSING`, `PAUSED`, `STOPPED`, and `COMPLETE` states, one `asyncio.Task`, monotonic maximum duration, jittered polling, capped exponential backoff, and credential/session cleanup on stop.

- [ ] **Step 4: Verify green**

Run `python3 -m pytest tests/test_scheduler.py -q`; expect all scheduler tests to pass.

### Task 7: Local Web API

**Files:**
- Create: `src/qfnu_course_web/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing route tests**

Test `/` returns the session token in a meta element, `/api/state` returns the snapshot, writes without the `X-QFNU-Token` header return 403, foreign `Origin` returns 403, captcha bytes appear only as a data URL, login responses never contain a password, target CRUD validates input, repeated start remains idempotent, pause and stop call the scheduler, YAML import rejects credentials and unknown fields, export contains only targets/runtime settings, and `/api/events` begins with a snapshot event.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_app.py -q`; expect an import failure for `qfnu_course_web.app`.

- [ ] **Step 3: Implement FastAPI routes**

Add local security middleware, lifecycle construction and cleanup, HTML/static mounting, auth endpoints, target CRUD, import/export, scheduler controls, state and SSE routes. Set `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `Cache-Control: no-store`, and frame denial headers.

- [ ] **Step 4: Verify green**

Run `python3 -m pytest tests/test_app.py -q`; expect all route tests to pass.

### Task 8: Responsive Console Interface

**Files:**
- Create: `src/qfnu_course_web/templates/index.html`
- Create: `src/qfnu_course_web/static/app.js`
- Create: `src/qfnu_course_web/static/styles.css`
- Create: `tests/test_ui_contract.py`

- [ ] **Step 1: Write failing UI contract tests**

Parse the rendered HTML and assert there is one `h1`, status regions use `aria-live`, every input has a label, icon buttons have accessible names and tooltips, tables have captions and headers, dialogs have headings, and script/style assets are local. Assert the viewport meta tag exists and no form stores a password value.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_ui_contract.py -q`; expect missing-template failures.

- [ ] **Step 3: Implement the console**

Build a quiet operations interface with a compact header, status strip, target table, candidate table, task list and event panel. Use neutral surfaces, green for success, amber for waiting, red for errors and blue for active operations. At widths below 760px, replace wide tables with labeled row blocks and keep primary controls in a fixed non-overlapping action bar.

- [ ] **Step 4: Implement browser behavior**

Fetch the session token from the page, centralize authenticated JSON requests, render all data with `textContent`, reconnect SSE with bounded delay, implement login/captcha, CRUD dialogs, controls, filters and YAML file import/export, and disable controls based on scheduler state.

- [ ] **Step 5: Verify green**

Run `python3 -m pytest tests/test_ui_contract.py -q`; expect all UI contract tests to pass.

### Task 9: Entry Point, Documentation and End-to-End Verification

**Files:**
- Create: `src/qfnu_course_web/__main__.py`
- Create: `README.md`
- Create: `courses.example.yaml`
- Create: `tests/test_end_to_end.py`

- [ ] **Step 1: Write a failing mock end-to-end test**

Start the app with an injected mock transport, complete captcha login, import one ordinary and one lecture-plus-lab target, start the scheduler, stream state until both targets complete, and assert the mock received no overlapping requests, observed at least 0.5 seconds between consecutive requests at two requests per second, and received no request after confirmation.

- [ ] **Step 2: Verify red**

Run `python3 -m pytest tests/test_end_to_end.py -q`; expect failure because the entry point and app wiring are incomplete.

- [ ] **Step 3: Add startup and operator documentation**

Make `python -m qfnu_course_web` choose an available localhost port, launch Uvicorn, and open the browser once healthy. Document virtual environment setup, installation, launch, captcha flow, each screen, YAML fields, module coverage, the two-request-per-second cap, troubleshooting and how to stop the process. Provide a credential-free example configuration.

- [ ] **Step 4: Run all automated checks**

Run `python3 -m pytest -q` and expect all tests to pass. Run `python3 -m ruff check .` and expect no diagnostics.

- [ ] **Step 5: Verify the rendered app locally**

Start `python3 -m qfnu_course_web`, open the reported URL, and verify desktop at 1440x900 and mobile at 390x844: no blank areas, clipped text, overlapping controls, horizontal page overflow or console errors. Confirm login, target editing, start/pause/stop and SSE updates against the local mock mode without contacting the live host.
