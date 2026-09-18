const token = document.querySelector('meta[name="qfnu-token"]').content;
let state = null;
let automationConfig = null;
let roundsLoaded = false;
let roundsLoading = false;
let catalogLoading = false;

const byId = (id) => document.getElementById(id);
const modules = {
  bxxk: "必修", xxxk: "选修", bxqjhxk: "本学期计划",
  knjxk: "跨年级", fawxk: "计划外", ggxxkxk: "公选课",
};
const phases = {
  idle: "等待", waiting: "等待名额", searching: "搜索中", ready: "可提交",
  submitting: "提交中", verifying: "确认中", success: "成功", failed: "失败",
  skipped: "同组跳过",
};
const automationPhases = {
  idle: "空闲", signing_in: "正在登录", needs_captcha: "等待验证码",
  selecting_round: "选择轮次", waiting: "等待开始", running: "运行中",
  needs_attention: "需要处理", complete: "已完成",
};

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-QFNU-Token", token);
  if (options.body && typeof options.body !== "string") {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body.detail || body || `请求失败 (${response.status})`);
  return body;
}

function valueOrNull(value) {
  const text = String(value || "").trim();
  return text || null;
}

function textCell(label, text) {
  const cell = document.createElement("td");
  cell.dataset.label = label;
  cell.textContent = text === null || text === undefined || text === "" ? "未知" : text;
  return cell;
}

function badge(phase, message) {
  const node = document.createElement("span");
  const active = ["searching", "submitting", "verifying", "ready"].includes(phase);
  node.className = `badge ${phase === "success" ? "success" : phase === "failed" ? "error" : active ? "active" : "warning"}`;
  node.textContent = message || phases[phase] || phase;
  return node;
}

function statusFor(id) {
  return state.statuses.find((item) => item.target_id === id) || { phase: "idle", message: "等待启动" };
}

function renderTargets() {
  const body = byId("targets-body");
  body.replaceChildren();
  if (!state.targets.length) {
    const row = document.createElement("tr");
    const cell = textCell("", "请从上方课程目录添加课程，或按课程编号添加");
    cell.colSpan = 6;
    cell.className = "empty";
    row.append(cell);
    body.append(row);
  }
  state.targets.slice().sort((a, b) => a.priority - b.priority).forEach((target) => {
    const row = document.createElement("tr");
    const status = statusFor(target.id);
    row.append(
      textCell("优先级", String(target.priority)),
      textCell("模式 / 模块", `${target.mode === "advanced" ? "课程编号" : "目录"} · ${modules[target.module]}`),
      textCell("课程", [target.course_code, target.course_name, target.class_id].filter(Boolean).join(" · ")),
      textCell("教师 / 分组 / 互斥组", [target.teacher, target.lab_group, target.exclusive_group].filter(Boolean).join(" / ")),
    );
    const statusCell = document.createElement("td");
    statusCell.dataset.label = "状态";
    statusCell.append(badge(status.phase, status.message));
    row.append(statusCell);
    const actions = document.createElement("td");
    actions.dataset.label = "操作";
    actions.className = "row-actions";
    const commands = [["刷新", () => refreshTarget(target.id)]];
    if (target.mode === "advanced") commands.push(["编辑", () => openTarget(target)]);
    commands.push(["删除", () => deleteTarget(target.id)]);
    commands.forEach(([label, handler]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "row-button";
      button.textContent = label;
      button.addEventListener("click", handler);
      actions.append(button);
    });
    row.append(actions);
    body.append(row);
  });
  byId("target-count").textContent = `${state.targets.length} 项`;
}

function targetContains(candidate) {
  return state.targets.some((target) => {
    if (target.module !== candidate.module) return false;
    if (candidate.split_flag === 4) {
      return target.course_id === candidate.course_id && target.lab_group === candidate.lab_group;
    }
    return Boolean(candidate.class_id && target.class_id === candidate.class_id);
  });
}

function seatsText(candidate) {
  const value = (label, number) => `${label} ${number === null || number === undefined ? "未知" : number}`;
  return [value("容量", candidate.capacity), value("已选", candidate.enrolled), value("余量", candidate.remaining)].join(" / ");
}

function catalogAction(candidate) {
  const cell = document.createElement("td");
  cell.dataset.label = "操作";
  if (targetContains(candidate)) {
    cell.append(badge("success", "已添加"));
    return cell;
  }
  if (candidate.split_flag === 1) {
    cell.append(badge("waiting", "请选择实验分组"));
    return cell;
  }
  if (!candidate.catalog_id || !candidate.course_id || !candidate.class_id) {
    cell.append(badge("failed", "信息不完整"));
    return cell;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "row-button add-button";
  button.textContent = "添加到监控";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api("/api/targets/from-candidate", {
        method: "POST", body: { catalog_id: candidate.catalog_id, priority: 100 },
      });
      await Promise.all([loadState(), loadAutomationConfig()]);
      toast("已添加到监控");
    } catch (error) {
      toast(error.message);
      button.disabled = false;
    }
  });
  cell.append(button);
  return cell;
}

function renderCatalogStatuses() {
  const container = byId("catalog-statuses");
  container.replaceChildren();
  const counts = state.catalog_module_counts || {};
  const errors = state.catalog_module_errors || {};
  if (!state.catalog_loaded_at) {
    const message = document.createElement("span");
    message.className = "count";
    message.textContent = state.authenticated ? "选择轮次后加载课程" : "请先登录";
    container.append(message);
    return;
  }
  Object.entries(modules).forEach(([key, label]) => {
    const item = document.createElement("span");
    item.className = `module-status ${errors[key] ? "error" : ""}`;
    item.textContent = errors[key] ? `${label} · 失败` : `${label} · ${counts[key] || 0}`;
    if (errors[key]) item.title = errors[key];
    container.append(item);
  });
}

function renderCatalog() {
  const all = state.catalog_candidates || [];
  const query = byId("catalog-filter").value.trim().toLocaleLowerCase();
  const selectedModule = byId("catalog-module").value;
  const rows = all.filter((candidate) => {
    if (selectedModule && candidate.module !== selectedModule) return false;
    if (!query) return true;
    return [candidate.course_code, candidate.course_name, candidate.teacher]
      .filter(Boolean).some((value) => value.toLocaleLowerCase().includes(query));
  });
  const body = byId("catalog-body");
  body.replaceChildren();
  if (!rows.length) {
    const row = document.createElement("tr");
    const text = all.length ? "没有符合当前筛选的课程" : state.authenticated ? "点击“加载全部可选课”获取课程" : "登录后加载全部可选课程";
    const cell = textCell("", text);
    cell.colSpan = 10;
    cell.className = "empty";
    row.append(cell);
    body.append(row);
  }
  rows.forEach((candidate) => {
    const row = document.createElement("tr");
    const conflict = candidate.conflict || "无冲突";
    row.append(
      textCell("模块", modules[candidate.module]),
      textCell("课程", [candidate.course_code, candidate.course_name].filter(Boolean).join(" · ")),
      textCell("教师", candidate.teacher), textCell("学分", candidate.credits),
      textCell("开课单位 / 类别", [candidate.department, candidate.category].filter(Boolean).join(" / ")),
      textCell("校区", candidate.campus),
      textCell("时间 / 地点", [candidate.schedule, candidate.location].filter(Boolean).join(" · ")),
      textCell("人数", seatsText(candidate)),
      textCell("教学班 / 分组 / 冲突", [candidate.class_id, candidate.lab_group, conflict].filter(Boolean).join(" / ")),
      catalogAction(candidate),
    );
    body.append(row);
  });
  byId("catalog-count").textContent = rows.length === all.length ? `${all.length} 条` : `${rows.length} / ${all.length} 条`;
  byId("catalog-loaded-at").textContent = state.catalog_loaded_at ? `更新于 ${new Date(state.catalog_loaded_at).toLocaleString()}` : "尚未加载";
  renderCatalogStatuses();
}

function renderEvents() {
  const list = byId("events");
  list.replaceChildren();
  const events = state.events.slice().reverse();
  if (!events.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "等待操作";
    list.append(item);
    return;
  }
  events.forEach((event) => {
    const item = document.createElement("li");
    item.className = `event-item ${event.level}`;
    const time = document.createElement("time");
    time.textContent = new Date(event.timestamp).toLocaleTimeString();
    const message = document.createElement("p");
    message.textContent = event.message;
    item.append(time, message);
    list.append(item);
  });
}

function render() {
  if (!state) return;
  byId("session-status").textContent = state.authenticated ? `已登录 · ${state.username}` : "未登录";
  byId("round-status").textContent = state.round_name || state.round_id || "自动识别";
  byId("automation-status").textContent = automationPhases[state.automation] || state.automation;
  byId("rate-status").textContent = `${state.runtime.requests_per_second} 次/秒`;
  const active = ["signing_in", "needs_captcha", "selecting_round", "waiting", "running"].includes(state.automation);
  byId("logout").disabled = !state.authenticated;
  byId("start").disabled = !state.targets.length || active;
  byId("stop").disabled = !active && !["running", "paused", "scheduled"].includes(state.scheduler);
  byId("catalog-round").disabled = !state.authenticated || catalogLoading;
  byId("catalog-load").disabled = !state.authenticated || catalogLoading || !byId("catalog-round").value;
  byId("catalog-load").textContent = catalogLoading ? "正在加载…" : "加载全部可选课";
  const captchaDialog = byId("automation-captcha-dialog");
  if (state.automation === "needs_captcha" && state.captcha_data_url) {
    byId("automation-captcha-image").src = state.captcha_data_url;
    if (!captchaDialog.open) captchaDialog.showModal();
  } else if (captchaDialog.open) {
    captchaDialog.close();
  }
  renderTargets();
  renderCatalog();
  renderEvents();
}

function toast(message) {
  const node = byId("toast");
  node.textContent = message;
  node.classList.add("visible");
  setTimeout(() => node.classList.remove("visible"), 2500);
}

async function loadState() {
  state = await api("/api/state");
  render();
}

async function loadAutomationConfig() {
  automationConfig = await api("/api/automation/config");
  return automationConfig;
}

async function loadRounds() {
  if (!state?.authenticated || roundsLoading) return;
  roundsLoading = true;
  try {
    const result = await api("/api/rounds");
    const select = byId("catalog-round");
    const preferred = state.runtime.round_id || state.round_id;
    select.replaceChildren();
    if (!result.rounds.length) {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "没有可用选课轮次";
      select.append(placeholder);
    }
    result.rounds.forEach((round) => {
      const option = document.createElement("option");
      option.value = round.id;
      option.textContent = round.name === round.id ? round.id : `${round.name} · ${round.id}`;
      select.append(option);
    });
    if (preferred && result.rounds.some((round) => round.id === preferred)) {
      select.value = preferred;
    } else if (result.rounds.length) {
      select.value = result.rounds[0].id;
    }
    roundsLoaded = true;
  } finally {
    roundsLoading = false;
    render();
  }
}

async function loadCatalog() {
  const roundId = byId("catalog-round").value;
  if (!roundId) return;
  catalogLoading = true;
  render();
  try {
    await api("/api/courses/catalog", { method: "POST", body: { round_id: roundId } });
    await loadState();
    toast(`已加载 ${state.catalog_candidates.length} 条课程`);
  } catch (error) {
    toast(error.message);
  } finally {
    catalogLoading = false;
    render();
  }
}

async function refreshTarget(id) {
  try {
    await api(`/api/targets/${id}/refresh`, { method: "POST" });
    toast("课程状态已刷新");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteTarget(id) {
  if (!confirm("删除这个目标课程？")) return;
  try {
    await api(`/api/targets/${id}`, { method: "DELETE" });
    await Promise.all([loadState(), loadAutomationConfig()]);
  } catch (error) {
    toast(error.message);
  }
}

const targetFields = ["module", "priority", "course_code"];

function openTarget(target = null, defaultMode = "search") {
  byId("target-form").reset();
  byId("target-id").value = target?.id || "";
  byId("target-title").textContent = target ? "编辑编号目标" : "按课程编号抢课";
  byId("target-mode").value = target?.mode || defaultMode;
  targetFields.forEach((field) => {
    const element = byId(`target-${field.replaceAll("_", "-")}`);
    if (element) element.value = target?.[field] ?? (field === "priority" ? 100 : "");
  });
  byId("target-error").textContent = "";
  byId("target-dialog").showModal();
}

function targetPayload(form) {
  return {
    enabled: true, mode: form.get("mode"), module: form.get("module"),
    priority: Number(form.get("priority")),
    course_id: valueOrNull(form.get("course_id")),
    course_code: valueOrNull(form.get("course_code")),
    course_name: valueOrNull(form.get("course_name")),
    class_id: valueOrNull(form.get("class_id")),
    lecture_class_id: valueOrNull(form.get("lecture_class_id")),
    teacher: valueOrNull(form.get("teacher")),
    lab_group: valueOrNull(form.get("lab_group")),
    weekday: valueOrNull(form.get("weekday")),
    periods: valueOrNull(form.get("periods")),
    exclusive_group: valueOrNull(form.get("exclusive_group")),
  };
}

async function refreshCaptcha() {
  try {
    const result = await api("/api/auth/captcha", { method: "POST" });
    byId("captcha-image").src = result.captcha_data_url;
  } catch (error) {
    byId("login-error").textContent = error.message;
  }
}

function fillSettings() {
  const config = automationConfig;
  byId("automation-username").value = config.account.username || "";
  byId("ocr-attempts").value = config.auth.ocr_attempts;
  byId("keepalive-seconds").value = config.auth.keepalive_seconds;
  byId("keychain-password").value = "";
  byId("password-status").textContent = config.password_saved ? "密码已保存到钥匙串" : "未保存密码";
  byId("password-delete").disabled = !config.password_saved;
  byId("settings-error").textContent = "";
}

function settingsPayload() {
  const form = new FormData(byId("settings-form"));
  return {
    version: 1,
    account: { username: String(form.get("username") || "").trim() },
    auth: {
      ocr_url: null,
      ocr_attempts: Number(form.get("ocr_attempts")),
      keepalive_seconds: Number(form.get("keepalive_seconds")),
    },
    selection: {
      round_keywords: [],
      start_time: null,
      requests_per_second: 5,
      poll_interval_seconds: 0.1,
      max_runtime_minutes: null,
      term_id: null,
    },
    targets: state.targets,
  };
}

async function saveSettings() {
  automationConfig = await api("/api/automation/config", { method: "PUT", body: settingsPayload() });
  await loadState();
  fillSettings();
}

byId("login-open").addEventListener("click", () => {
  byId("login-error").textContent = "";
  byId("username").value = automationConfig?.account.username || "";
  byId("login-dialog").showModal();
  refreshCaptcha();
});
byId("logout").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    roundsLoaded = false;
    await loadState();
  } catch (error) { toast(error.message); }
});
byId("captcha-refresh").addEventListener("click", refreshCaptcha);
byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: { username: form.get("username"), password: form.get("password"), captcha: form.get("captcha") },
    });
    byId("password").value = "";
    byId("login-dialog").close();
    await loadState();
    await loadRounds();
  } catch (error) {
    byId("password").value = "";
    byId("login-error").textContent = error.message;
    refreshCaptcha();
  }
});
byId("automation-captcha-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/automation/captcha", { method: "POST", body: { captcha: byId("automation-captcha").value } });
    byId("automation-captcha").value = "";
    byId("automation-captcha-dialog").close();
  } catch (error) { byId("automation-captcha-error").textContent = error.message; }
});
byId("target-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = byId("target-id").value;
  try {
    await api(id ? `/api/targets/${id}` : "/api/targets", {
      method: id ? "PUT" : "POST", body: targetPayload(new FormData(event.currentTarget)),
    });
    byId("target-dialog").close();
    await Promise.all([loadState(), loadAutomationConfig()]);
  } catch (error) { byId("target-error").textContent = error.message; }
});
byId("advanced-target-open").addEventListener("click", () => openTarget(null, "advanced"));
byId("catalog-load").addEventListener("click", loadCatalog);
byId("catalog-round").addEventListener("change", render);
byId("catalog-filter").addEventListener("input", renderCatalog);
byId("catalog-module").addEventListener("change", renderCatalog);
byId("settings-open").addEventListener("click", async () => {
  try {
    await loadAutomationConfig();
    fillSettings();
    byId("settings-dialog").showModal();
  } catch (error) { toast(error.message); }
});
byId("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveSettings();
    byId("settings-dialog").close();
    toast("自动化设置已保存");
  } catch (error) { byId("settings-error").textContent = error.message; }
});
byId("password-save").addEventListener("click", async () => {
  const password = byId("keychain-password").value;
  try {
    await saveSettings();
    await api("/api/automation/password", { method: "PUT", body: { password } });
    byId("keychain-password").value = "";
    await loadAutomationConfig();
    fillSettings();
  } catch (error) {
    byId("keychain-password").value = "";
    byId("settings-error").textContent = error.message;
  }
});
byId("password-delete").addEventListener("click", async () => {
  try {
    await api("/api/automation/password", { method: "DELETE" });
    await loadAutomationConfig();
    fillSettings();
  } catch (error) { byId("settings-error").textContent = error.message; }
});
byId("start").addEventListener("click", async () => {
  try {
    await api("/api/automation/start", { method: "POST" });
    toast("自动工作流已启动");
  } catch (error) { toast(error.message); }
});
byId("stop").addEventListener("click", async () => {
  try {
    await api("/api/scheduler/stop", { method: "POST" });
  } catch (error) { toast(error.message); }
});
byId("clear-events").addEventListener("click", () => { state.events = []; renderEvents(); });
document.querySelectorAll(".close-dialog").forEach((button) => {
  button.addEventListener("click", () => button.closest("dialog").close());
});

const stream = new EventSource("/api/events");
stream.addEventListener("snapshot", (event) => {
  state = JSON.parse(event.data);
  render();
  if (state.authenticated && !roundsLoaded) loadRounds().catch((error) => toast(error.message));
  if (!state.authenticated) roundsLoaded = false;
});
stream.addEventListener("event", (event) => {
  if (!state) return;
  state.events.push(JSON.parse(event.data));
  renderEvents();
});
stream.onerror = () => toast("事件连接正在重连");
Promise.all([loadState(), loadAutomationConfig()])
  .then(() => state.authenticated ? loadRounds() : null)
  .catch((error) => toast(error.message));
