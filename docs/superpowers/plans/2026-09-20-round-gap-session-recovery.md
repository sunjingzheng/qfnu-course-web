# Round-gap Session Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep course automation running when the authenticated session expires while the course-round list is temporarily empty.

**Architecture:** Teach both round-wait loops to recognize `SessionExpiredError`, invoke their existing reauthentication callback/path, report recovery events, and resume polling. Preserve the existing behavior for empty rounds, remote-login errors, and unrecoverable authentication failures.

**Tech Stack:** Python 3.11+, asyncio, pytest, FastAPI application services

---

### Task 1: Running scheduler recovery

**Files:**
- Modify: `tests/test_scheduler.py`
- Modify: `src/qfnu_course_web/scheduler.py`

- [x] **Step 1: Write the failing test**

Add a scheduler test whose round resolver returns an old round, then an empty-list error, then a session-expired error, and finally a new round. Assert that reauthentication occurs once, the new round is entered, and the target completes.

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_scheduler.py::test_scheduler_reauthenticates_while_waiting_for_a_round`

Expected: FAIL because the session-expired error escapes `_wait_for_available_round`, no reauthentication occurs, and the scheduler stops.

- [x] **Step 3: Write minimal implementation**

Catch `SessionExpiredError` inside `CourseScheduler._wait_for_available_round`, call the existing `reauthenticate` callback, emit the same session recovery events used by the main scheduler loop, and resume round polling after a successful login.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/test_scheduler.py::test_scheduler_reauthenticates_while_waiting_for_a_round`

Expected: PASS.

### Task 2: Initial automation recovery

**Files:**
- Modify: `tests/test_automation.py`
- Modify: `src/qfnu_course_web/automation.py`

- [x] **Step 1: Write the failing test**

Add an automation test whose catalog first has no round, then raises `SessionExpiredError`, then exposes a new round. Assert that automatic login runs again and scheduling begins with the new round.

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_automation.py::test_automation_reauthenticates_while_waiting_for_a_round`

Expected: FAIL because `_wait_for_available_round` currently handles only `RoundSelectionError`.

- [x] **Step 3: Write minimal implementation**

Catch `SessionExpiredError` in `AutomationController._wait_for_available_round`, call `_recover_session`, log recovery, and continue polling.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q tests/test_automation.py::test_automation_reauthenticates_while_waiting_for_a_round`

Expected: PASS.

### Task 3: Verify, publish, and synchronize

**Files:**
- Verify: `src/qfnu_course_web/scheduler.py`
- Verify: `src/qfnu_course_web/automation.py`
- Verify: `tests/test_scheduler.py`
- Verify: `tests/test_automation.py`

- [x] **Step 1: Run the full suite and lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`

Expected: all tests pass and Ruff reports no errors.

- [x] **Step 2: Review the diff**

Run: `git diff --check && git diff -- src/qfnu_course_web tests docs/superpowers/plans`

Expected: focused changes with no whitespace errors or unrelated files.

- [ ] **Step 3: Commit and push**

Commit the implementation and tests on `main`, then push `main` to `origin`.

- [ ] **Step 4: Synchronize local runtime copies**

Fast-forward `/Users/mac/Documents/test1/qfnu-course-web/qfnu-course-web` and `/Users/mac/Documents/test2` to the pushed commit, then run their targeted recovery tests.
