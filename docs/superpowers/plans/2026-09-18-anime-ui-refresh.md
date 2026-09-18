# 月夜电波控制台 UI 改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有选课控制台改造成不依赖图片生成或外部资源的原创二次元月夜终端界面。

**Architecture:** 保持现有 FastAPI、HTML 结构和 JavaScript 行为，只在模板加入无语义装饰层与主题类，并重写 CSS 视觉系统。所有装饰由 CSS 生成，业务控件、DOM ID、表格列和 API 行为不变。

**Tech Stack:** Jinja2 HTML、原生 CSS、原生 JavaScript、BeautifulSoup UI 合约测试、Playwright CLI

---

### Task 1: 锁定主题结构契约

**Files:**
- Modify: `tests/test_ui_contract.py`
- Test: `tests/test_ui_contract.py`

- [x] 添加断言：`body` 包含 `lunar-console` 类，存在 `#cosmic-backdrop[aria-hidden=true]`，标题区包含 `月面电波终端`，并继续断言所有既有操作控件存在。
- [x] 运行 `.venv/bin/python -m pytest -q tests/test_ui_contract.py`，确认模板修改前测试失败。

### Task 2: 增加非交互主题标记

**Files:**
- Modify: `src/qfnu_course_web/templates/index.html`
- Test: `tests/test_ui_contract.py`

- [x] 为 `body` 添加 `lunar-console` 类，并在正文前加入 `#cosmic-backdrop` 装饰层，包含星野、月弧、轨道线和扫描线四个 `aria-hidden` 子层。
- [x] 将标题眉标改为 `LUNAR SIGNAL / COURSE CONTROL`，在产品名下加入短标签 `月面电波终端`；不改变任何业务 DOM ID。
- [x] 运行 UI 合约测试，确认通过。

### Task 3: 实现月夜电波视觉系统

**Files:**
- Modify: `src/qfnu_course_web/static/styles.css`

- [x] 重建 CSS 变量：月白背景、深色正文、玫红主操作、电青状态、绿黄红语义色。
- [x] 使用伪元素与 CSS 背景绘制固定星野、斜向轨道线、月面切线和低透明扫描线；设置 `pointer-events: none`。
- [x] 为标题栏、状态条、命令栏、课程工具栏、表格、事件流和对话框加入高对比半透明亮色表面。
- [x] 为按钮、表格行、状态徽标和输入焦点增加清晰的悬停与键盘反馈；圆角保持 6px 以内。
- [x] 保持 1100、960、760 像素现有断点，在手机端降低装饰透明度并确保底部命令栏不遮挡内容。
- [x] 增加 `prefers-reduced-motion: reduce`，关闭加载、扫描和呼吸动画。

### Task 4: 自动化验证与视觉 QA

**Files:**
- Modify only if QA reveals a concrete issue: `src/qfnu_course_web/static/styles.css`

- [x] 运行 `.venv/bin/python -m pytest -q`、Ruff、格式检查和 `node --check src/qfnu_course_web/static/app.js`。
- [x] 重启 `http://127.0.0.1:8765/`。
- [x] 使用 Playwright 在 1440x900 与 390x844 截图，检查背景非空、表格文字对比、控件溢出、对话框与固定底栏。
- [x] 对发现的重叠或可读性问题做最小 CSS 修正并重新截图确认。
