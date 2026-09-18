# 全部可选课程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 登录后加载六个选课模块的课程详情，并允许用户从课程目录逐条添加监控目标。

**Architecture:** `CourseCatalog` 继续负责单模块请求，新建目录服务负责编排轮次和六模块查询、缓存最近目录并从可信缓存构造目标。FastAPI 暴露轮次、目录和添加目标接口；浏览器只传候选索引，在内存中筛选和渲染结果。

**Tech Stack:** Python 3.11+、FastAPI、httpx、Pydantic、原生 HTML/CSS/JavaScript、pytest、Playwright CLI。

---

### Task 1: 扩展课程数据模型

**Files:** `src/qfnu_course_web/models.py`、`src/qfnu_course_web/courses.py`、`tests/test_courses.py`

- [x] 在 `CourseCandidate` 增加 `catalog_id`、`credits`、`department` 和 `category`，并添加允许空条件的 `CourseQuery`。
- [x] 用响应中的 `xf`、`dwmc`、`szkcflmc` 填充详情字段。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_courses.py`，确认解析测试通过。

### Task 2: 实现全模块目录服务

**Files:** `src/qfnu_course_web/catalog.py`、`src/qfnu_course_web/app.py`、`tests/test_catalog.py`

- [x] 实现 `CatalogService.load(round_id)`，进入轮次后按 `MODULES` 顺序进入模块并查询空条件课程。
- [x] 为结果分配进程内索引并缓存索引到候选的映射；单模块错误写入结果，会话类错误继续抛出。
- [x] 实现 `target_from_candidate(index, priority, targets)`：普通课锁定教学班，实验行保存实验分组，讲课行存在实验配对时拒绝添加，并检测重复目标。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_catalog.py`，确认目录顺序、部分失败和转换测试通过。

### Task 3: 暴露目录 API

**Files:** `src/qfnu_course_web/app.py`、`src/qfnu_course_web/state.py`、`tests/test_app.py`

- [x] 添加 `GET /api/rounds`，要求令牌和登录状态。
- [x] 添加 `POST /api/courses/catalog`，验证轮次后返回候选和模块错误，并更新候选状态。
- [x] 添加 `POST /api/targets/from-candidate`，只接收目录索引和优先级，通过目录缓存创建目标。
- [x] 退出登录时清空目录缓存和候选状态。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_app.py`，确认认证、调用顺序和可信索引测试通过。

### Task 4: 构建课程目录界面

**Files:** `src/qfnu_course_web/templates/index.html`、`src/qfnu_course_web/static/app.js`、`src/qfnu_course_web/static/styles.css`、`tests/test_ui_contract.py`

- [x] 移除“新增课程”按钮和空白课程表单，增加只编辑优先级的对话框。
- [x] 增加轮次、加载按钮、本地关键字与模块筛选、模块状态和最后加载时间。
- [x] 渲染全部课程详情，为可添加行创建“添加到监控”按钮，为已添加行显示状态。
- [x] 添加响应式目录工具栏和移动端表格标签。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_ui_contract.py`，确认可访问性和控件合约通过。

### Task 5: 文档与端到端验证

**Files:** `README.md`

- [x] 更新操作流程及教务接口空查询限制。
- [x] 运行 `.venv/bin/python -m pytest -q`、`.venv/bin/python -m ruff check .` 和 `.venv/bin/python -m ruff format --check .`。
- [x] 重启本地服务并确认首页、favicon、空状态和默认每秒 2 次。
- [x] 用 Playwright 检查桌面与移动布局、模拟目录的添加流程和浏览器控制台。
