# 自动登录与定时抢课 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为本地选课控制台增加钥匙串凭据、OCR 自动登录、轮次关键字、定时启动、会话恢复、高级目标和互斥分组。

**Architecture:** 使用 `ConfigStore` 和 `KeychainStore` 隔离持久化与凭据；`AuthService` 扩展 OCR 和会话验证；`AutomationController` 负责编排自动登录、轮次选择、定时等待和调度器。现有 `CourseScheduler` 继续执行课程循环，但增加高级直提、重登录回调和互斥组状态。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、httpx、macOS `security` CLI、原生 HTML/CSS/JavaScript、pytest、Playwright CLI。

---

### Task 1: 配置文件与钥匙串

**Files:** `src/qfnu_course_web/config.py`、`src/qfnu_course_web/keychain.py`、`src/qfnu_course_web/models.py`、`.gitignore`、`tests/test_config.py`、`tests/test_keychain.py`

- [x] 写失败测试覆盖默认 `config.json`、`0600` 权限、原子保存、损坏文件、密码字段拒绝和钥匙串保存/读取/删除。
- [x] 实现版本化 `AppConfig`、`AccountConfig`、`AuthConfig`、`SelectionConfig` 和 `ConfigStore`。
- [x] 实现注入命令执行器的 `KeychainStore`，调用 `security add-generic-password`、`find-generic-password` 和 `delete-generic-password`。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_config.py tests/test_keychain.py`。

### Task 2: OCR 自动登录与会话检查

**Files:** `src/qfnu_course_web/auth.py`、`tests/test_auth.py`

- [x] 写失败测试覆盖 OCR 响应、验证码重试、手动回退和学生主页会话验证。
- [x] 拆分验证码字节获取与 data URL，增加 `recognize_captcha`、`automatic_login`、`check_session`。
- [x] 自动登录仅从调用方接收密码，不保存凭据；验证码错误按次数重试，OCR 不可用抛出可识别错误。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_auth.py`。

### Task 3: 轮次名称与关键字匹配

**Files:** `src/qfnu_course_web/rounds.py`、`src/qfnu_course_web/courses.py`、`tests/test_rounds.py`、`tests/test_courses.py`

- [x] 写失败测试覆盖链接文字解析、名称退化、关键字优先级、唯一轮次、无匹配和同优先级多匹配。
- [x] 实现 `RoundOption`、`parse_rounds` 和 `select_round`，并让 `CourseCatalog.list_rounds()` 返回结构化轮次。
- [x] 更新目录、调度和 API 调用方使用 `RoundOption.id`。
- [x] 运行相关测试。

### Task 4: 定时自动化控制器

**Files:** `src/qfnu_course_web/automation.py`、`src/qfnu_course_web/models.py`、`src/qfnu_course_web/state.py`、`tests/test_automation.py`

- [x] 写失败测试覆盖过去时间拒绝、未来等待、保活、停止中断、自动登录和人工验证码状态。
- [x] 增加计划开始时间、倒计时、认证阶段和所选轮次名称状态。
- [x] 实现 `AutomationController` 后台任务，按配置登录、选择轮次、等待并调用调度器。
- [x] 在等待期间按配置验证会话并在失效时重登录。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_automation.py`。

### Task 5: 高级模式、互斥组和会话恢复

**Files:** `src/qfnu_course_web/models.py`、`src/qfnu_course_web/scheduler.py`、`src/qfnu_course_web/enrollment.py`、`tests/test_models.py`、`tests/test_scheduler.py`、`tests/test_enrollment.py`

- [x] 写失败测试覆盖高级字段校验、直接提交、实验组合、同组成功跳过、未验证不跳过和会话重登录重试。
- [x] 扩展 `CourseTarget` 的 `mode`、`lecture_class_id` 和 `exclusive_group`，增加 `TaskPhase.SKIPPED`。
- [x] 高级目标跳过搜索并构造普通或讲课实验匹配。
- [x] 验证成功后移除同组目标；会话失效调用重登录回调并重新进入轮次和模块。
- [x] 运行调度与选课测试。

### Task 6: 配置和自动化 API

**Files:** `src/qfnu_course_web/app.py`、`tests/test_app.py`

- [x] 写失败测试覆盖配置读取保存、钥匙串状态、密码保存删除、自动启动、手动验证码恢复和敏感数据不回传。
- [x] 在服务启动时加载或生成 `config.json`，同步运行配置和目标。
- [x] 增加 `/api/automation/config`、`/api/automation/password`、`/api/automation/start` 和人工验证码接口。
- [x] 保留现有手动登录和调度接口兼容性。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_app.py`。

### Task 7: Web 配置界面

**Files:** `src/qfnu_course_web/templates/index.html`、`src/qfnu_course_web/static/app.js`、`src/qfnu_course_web/static/styles.css`、`tests/test_ui_contract.py`

- [x] 写失败 UI 合约测试覆盖自动化设置、钥匙串操作、轮次关键字、开始时间、高级模式和互斥组。
- [x] 增加自动化配置对话框和保存状态，密码只在提交时读取并立即清空。
- [x] 增加计划时间、倒计时和认证阶段状态；“开始监控”改为启动自动工作流。
- [x] 增加搜索/高级目标编辑；课程目录添加目标仍为默认路径。
- [x] 完成桌面和移动响应式布局。

### Task 8: 文档与验证

**Files:** `README.md`、`config.example.json`

- [x] 更新安装、钥匙串、OCR、自动工作流、搜索/高级模式和互斥组说明。
- [x] 运行完整 pytest、Ruff 检查、格式检查和 JavaScript 语法检查。
- [x] 重启本地服务并确认默认配置文件权限、HTTP 状态和敏感字段不出现在响应。
- [ ] 用 Playwright 检查桌面、移动、配置表单、目标模式和模拟自动状态，确认控制台无错误。（当前机器未安装 Playwright 浏览器，应用内浏览器因锁屏和连接认证不可控。）
