const config = window.ONCALL_CONFIG || {};

const state = {
  scenarios: [],
  health: null,
  dashboard: null,
  runs: [],
  activeRun: null,
  knowledgeStatus: null,
  knowledgeDocuments: [],
  chatMessages: [],
  chatTrace: [],
  loading: true,
  error: null,
  sessionId: getSessionId(),
};

const app = document.querySelector("#app");

function getSessionId() {
  const key = "oncall-agent-session";
  let value = localStorage.getItem(key);
  if (!value) {
    value = `web-${crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36)}`;
    localStorage.setItem(key, value);
  }
  return value;
}

function icon(name, size = 18) {
  const paths = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    shield: '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3z"/><path d="M9 12l2 2 4-4"/>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    activity: '<path d="M4 17l5-5 3 3 7-8"/><path d="M14 7h5v5"/>',
    code: '<path d="M8 9l-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"/>',
    arrow: '<path d="M5 12h14M14 7l5 5-5 5"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    check: '<path d="M5 12l4 4L19 6"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    chevron: '<path d="M9 18l6-6-6-6"/>',
    terminal: '<path d="M4 17l5-5-5-5M11 19h9"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1-1"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    layers: '<path d="M12 3L3 8l9 5 9-5-9-5z"/><path d="M3 12l9 5 9-5M3 16l9 5 9-5"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  };
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.activity}</svg>`;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function formatDate(value, options = {}) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...options,
  }).format(date);
}

function severityClass(severity) {
  return (severity || "unknown").toLowerCase().replace("-", "");
}

function impactLabel(impact) {
  return { critical: "严重", major: "高", minor: "中", none: "低" }[impact] || "未知";
}

function statusLabel(status) {
  return {
    resolved: "已恢复",
    investigating: "调查中",
    identified: "已定位",
    monitoring: "监控中",
    "awaiting-approval": "待审批",
    completed: "已完成",
    approved: "已批准",
    rejected: "已拒绝",
    blocked: "已阻断",
  }[status] || status || "未知";
}

async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const localHost = ["localhost", "127.0.0.1"].includes(location.hostname);
  const baseUrl = (localHost ? "" : (config.apiBaseUrl || "")).replace(/\/$/, "");
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { ...(!isForm ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
  });
  let body = null;
  try { body = await response.json(); } catch (_) { body = null; }
  if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
  return body;
}

async function loadData() {
  try {
    const [health, scenarios, dashboard, runs] = await Promise.all([
      api("/api/health"),
      api("/api/scenarios"),
      api("/api/dashboard"),
      api(`/api/runs?session_id=${encodeURIComponent(state.sessionId)}`),
    ]);
    Object.assign(state, { health, scenarios, dashboard, runs, loading: false, error: null });
  } catch (error) {
    Object.assign(state, { loading: false, error: error.message });
  }
  renderRoute();
}

function landingHeader() {
  return `
    <header class="landing-header shell">
      <a class="brand" href="#landing" aria-label="OnCall Agent 首页"><span class="brand-glyph">OC</span><span>OnCall <b>Agent</b></span></a>
      <nav><a href="#capabilities">能力</a><a href="#incidents">真实数据</a><a href="#architecture">架构</a></nav>
      <div class="header-actions"><span class="runtime-pill"><i></i>${state.dashboard?.data_mode || "connecting"}</span><a class="text-link" href="#home">打开控制台 ${icon("arrow", 14)}</a></div>
    </header>`;
}

function renderLanding() {
  document.body.className = "page-landing";
  app.innerHTML = `
    ${landingHeader()}
    <main>
      <section class="landing-hero shell">
        <div class="hero-copy">
          <span class="eyebrow"><i></i> REAL INCIDENT RESPONSE RUNTIME</span>
          <h1>让每一次故障，<em>都留下可验证的答案。</em></h1>
          <p>OnCall Agent 从真实公开事故中提取证据，生成可证伪的根因假设，并在任何生产动作之前执行人工审批门控。</p>
          <div class="hero-buttons"><a class="button primary" href="#home">进入事故控制台 ${icon("arrow", 16)}</a><a class="button secondary" href="#incidents">查看真实事故</a></div>
          <div class="hero-footnote"><span>${icon("shield", 15)} 不执行生产写操作</span><span>${icon("link", 15)} 每条证据可追溯</span></div>
        </div>
        <div class="hero-runtime" aria-label="OnCall Agent execution preview">
          <div class="runtime-window">
            <div class="runtime-bar"><span><i></i><i></i><i></i></span><b>agent_run.trace</b><small>LIVE</small></div>
            <div class="runtime-incident"><span class="severity-badge sev1">SEV-1</span><div><small>INCIDENT REPLAY</small><strong>GitHub service degradation</strong></div><span class="source-chip">GitHub Status</span></div>
            <div class="agent-flow">
              <div class="flow-node active"><span>01</span><div><b>Observe</b><small>normalize public signals</small></div><i></i></div>
              <div class="flow-line"></div>
              <div class="flow-node active"><span>02</span><div><b>Diagnose</b><small>rank testable causes</small></div><i></i></div>
              <div class="flow-line"></div>
              <div class="flow-node guarded"><span>03</span><div><b>Safety gate</b><small>human approval required</small></div><i></i></div>
            </div>
            <div class="runtime-result"><div><span>PRIMARY HYPOTHESIS</span><strong>Downstream dependency degradation</strong></div><b>74%</b></div>
          </div>
          <div class="floating-card card-source"><span>${icon("database", 17)}</span><div><b>Real source</b><small>statuspage API</small></div></div>
          <div class="floating-card card-policy"><span>${icon("shield", 17)}</span><div><b>Policy gated</b><small>no auto-remediation</small></div></div>
        </div>
      </section>

      <section class="proof-row shell">
        <div><strong>${state.dashboard?.incident_count ?? "—"}</strong><span>真实事故回放</span></div>
        <div><strong>${state.dashboard?.source_name || "GitHub Status"}</strong><span>公开数据源</span></div>
        <div><strong>5</strong><span>可审计工具阶段</span></div>
        <div><strong>0</strong><span>自动生产写操作</span></div>
      </section>

      <section class="capability-section shell" id="capabilities">
        <div class="section-heading"><div><span>ONCALL CONTROL PLANE</span><h2>不是聊天框，<br/>是受约束的 Agent Runtime。</h2></div><p>观察、证据、假设、动作和授权严格分层。每个阶段都能被测试、回放和审计。</p></div>
        <div class="capability-grid">
          <article class="cap-card violet"><div class="cap-icon">${icon("database", 25)}</div><span>01 / CONNECT</span><h3>真实事故连接器</h3><p>服务端读取固定白名单 GitHub Status API，失败时回退到带来源链接的验证快照。</p><footer>Live + replay ${icon("arrow", 15)}</footer></article>
          <article class="cap-card orange"><div class="cap-icon">${icon("layers", 25)}</div><span>02 / REASON</span><h3>证据约束诊断</h3><p>模型只能引用已编号证据；缺少区分性遥测时，系统明确降低置信度并请求补充数据。</p><footer>Evidence first ${icon("arrow", 15)}</footer></article>
          <article class="cap-card blue"><div class="cap-icon">${icon("activity", 25)}</div><span>03 / TRACE</span><h3>完整执行轨迹</h3><p>工具调用、目的、输出摘要、时延和只读属性进入同一条 Agent Run，可直接检查。</p><footer>Observable loop ${icon("arrow", 15)}</footer></article>
          <article class="cap-card green"><div class="cap-icon">${icon("shield", 25)}</div><span>04 / GOVERN</span><h3>人工审批门控</h3><p>置信度从不等于授权。高风险建议进入审批或阻断状态，公开实例不执行任何恢复操作。</p><footer>Human in control ${icon("arrow", 15)}</footer></article>
        </div>
      </section>

      <section class="incident-section" id="incidents"><div class="shell">
        <div class="section-heading compact"><div><span>LIVE INCIDENT FEED</span><h2>从真实事故开始调查</h2></div><p>每条记录保留来源、事故 ID、时间线与数据新鲜度。</p></div>
        <div id="landing-incidents" class="landing-incidents"></div>
        <a class="wide-link" href="#home"><span>打开完整事故控制台</span>${icon("arrow", 18)}</a>
      </div></section>

      <section class="architecture-section shell" id="architecture">
        <div class="section-heading"><div><span>EXECUTION MODEL</span><h2>五个工具阶段，<br/>一条可验证路径。</h2></div><p>Agent 运行不是隐藏的黑箱。每个工具只承担一个明确职责，并在最终建议前通过策略门控。</p></div>
        <div class="architecture-flow">
          ${["github_status.read","evidence.normalize","diagnosis.rank","citations.validate","policy.gate"].map((item, index) => `<div class="arch-node"><span>0${index + 1}</span><b>${item}</b><small>${["读取事故","规范证据","排序假设","验证引用","风险决策"][index]}</small></div>${index < 4 ? '<i>→</i>' : ''}`).join("")}
        </div>
      </section>

      <section class="landing-cta"><div><span>START AN INVESTIGATION</span><h2>把真实事故放进<br/>可审计的 Agent Loop。</h2><a class="button dark" href="#/customer-service">进入 Agent 工作台 ${icon("arrow", 17)}</a></div></section>
    </main>
    <footer class="landing-footer shell"><div class="brand"><span class="brand-glyph">OC</span><span>OnCall Agent</span></div><p>Evidence-grounded incident response · Railway deployment</p><a href="${config.repositoryUrl || "#"}" target="_blank" rel="noopener noreferrer">Source ${icon("external", 13)}</a></footer>`;
  renderIncidentCards(document.querySelector("#landing-incidents"), state.scenarios.slice(0, 3), true);
}

function renderIncidentCards(container, items, landing = false) {
  if (!container) return;
  container.replaceChildren();
  if (!items.length) {
    container.append(node("p", "empty-copy", state.error || "暂无事故数据"));
    return;
  }
  items.forEach((scenario, index) => {
    const article = node("article", landing ? "incident-preview" : "incident-row");
    const meta = node("div", "incident-meta");
    const severity = node("span", `severity-badge ${severityClass(scenario.request.severity)}`, scenario.request.severity);
    const source = node("span", "source-chip", scenario.data_mode);
    meta.append(severity, source);
    const title = node("h3", "", scenario.title);
    const description = node("p", "", scenario.request.description);
    const facts = node("div", "incident-facts");
    [scenario.request.service, `${scenario.update_count} updates`, formatDate(scenario.started_at)].forEach((text, factIndex) => {
      const span = node("span", "");
      span.innerHTML = factIndex === 2 ? icon("clock", 13) : factIndex === 1 ? icon("activity", 13) : icon("database", 13);
      span.append(document.createTextNode(text));
      facts.append(span);
    });
    const footer = node("footer", "");
    const status = node("span", `incident-status ${scenario.incident_status}`, statusLabel(scenario.incident_status));
    const link = node("a", "incident-open", landing ? "开始调查" : "打开事故");
    link.href = `#/incidents/${encodeURIComponent(scenario.key)}`;
    link.insertAdjacentHTML("beforeend", icon("arrow", 14));
    footer.append(status, link);
    article.append(meta, title, description, facts, footer);
    article.style.setProperty("--delay", `${index * 70}ms`);
    container.append(article);
  });
}

function appSidebar(active = "home") {
  return `<aside class="app-sidebar">
    <a class="sidebar-brand" href="#landing"><span>OC</span></a>
    <nav>
      <a class="${active === "home" ? "active" : ""}" href="#home" title="事故控制台">${icon("grid", 20)}</a>
      <a class="${active === "runs" ? "active" : ""}" href="#home#runs" title="Agent Runs">${icon("pulse", 20)}</a>
      <a href="#landing#architecture" title="系统架构">${icon("layers", 20)}</a>
    </nav>
    <div class="sidebar-bottom"><span class="live-orb" title="Runtime online"></span><button title="Session">${icon("user", 18)}</button></div>
  </aside>`;
}

function appTopbar(title = "事故控制台") {
  return `<header class="app-topbar">
    <div><button class="mobile-menu">${icon("menu", 18)}</button><a href="#landing">OnCall Agent</a><i>/</i><strong>${title}</strong></div>
    <div class="topbar-right"><span class="runtime-pill"><i></i>${state.dashboard?.data_mode || state.health?.incident_data_mode || "online"}</span><button>${icon("search", 17)}</button><button>${icon("bell", 17)}</button><span class="avatar">OP</span></div>
  </header>`;
}

function renderDashboard() {
  document.body.className = "page-app";
  app.innerHTML = `<div class="app-frame">${appSidebar("home")}<div class="app-main">${appTopbar("事故控制台")}
    <main class="dashboard shell-app">
      <section class="dashboard-heading"><div><span>INCIDENT OPERATIONS</span><h1>事故控制台</h1><p>选择真实事故启动 Agent Run，或提交你自己的脱敏遥测。</p></div><button class="button primary" id="new-incident">${icon("plus", 16)} 新建调查</button></section>
      <section class="metric-grid">
        <article><span>真实事故</span><strong>${state.dashboard?.incident_count ?? state.scenarios.length}</strong><small>${state.dashboard?.source_name || "GitHub Status"} · ${state.dashboard?.data_mode || "—"}</small><i class="metric-icon purple">${icon("database", 20)}</i></article>
        <article><span>未解决事件</span><strong>${state.dashboard?.unresolved_count ?? 0}</strong><small>基于公开状态字段</small><i class="metric-icon orange">${icon("pulse", 20)}</i></article>
        <article><span>本次会话 Runs</span><strong>${state.runs.length}</strong><small>进程内审计记录</small><i class="metric-icon blue">${icon("terminal", 20)}</i></article>
        <article><span>待审批</span><strong>${state.runs.filter((run) => run.status === "awaiting-approval").length}</strong><small>不会自动执行动作</small><i class="metric-icon green">${icon("shield", 20)}</i></article>
      </section>
      <section class="dashboard-grid">
        <div class="panel incident-panel"><header><div><span>REAL INCIDENTS</span><h2>GitHub Status 事故流</h2></div><span class="sync-label"><i></i>${state.dashboard?.data_mode || "loading"}</span></header><div id="dashboard-incidents" class="dashboard-incidents"></div></div>
        <aside class="dashboard-side">
          <section class="panel runtime-card"><header><div><span>RUNTIME</span><h2>Agent 状态</h2></div><span class="healthy-chip">在线</span></header>
            <div class="runtime-brand"><span>OC</span><div><strong>${state.health?.model || "model"}</strong><small>${state.health?.deepseek_configured ? "LLM configured" : "Deterministic fallback"}</small></div></div>
            <dl><div><dt>证据连接器</dt><dd>GitHub Status</dd></div><div><dt>工具阶段</dt><dd>5</dd></div><div><dt>写操作权限</dt><dd>禁用</dd></div><div><dt>运行存储</dt><dd>Process-local</dd></div></dl>
          </section>
          <section class="panel run-history" id="runs"><header><div><span>SESSION MEMORY</span><h2>最近运行</h2></div><span>${state.runs.length}</span></header><div id="run-list"></div></section>
        </aside>
      </section>
    </main></div></div>
    <div class="modal" id="incident-modal" hidden><div class="modal-backdrop" data-close></div><form class="modal-card" id="incident-form"><header><div><span>CUSTOM INCIDENT</span><h2>新建脱敏调查</h2></div><button type="button" data-close>${icon("x", 18)}</button></header><p>提交描述和最小上下文。请勿上传密码、令牌、个人信息或生产机密。</p><label>服务名称<input name="service" maxlength="120" value="unknown-service" required></label><label>严重级别<select name="severity"><option>SEV-1</option><option selected>SEV-2</option><option>SEV-3</option><option>UNKNOWN</option></select></label><label>事故描述<textarea name="description" minlength="10" maxlength="6000" rows="7" placeholder="描述症状、影响、时间窗口和已有遥测…" required></textarea></label><footer><button type="button" class="button secondary" data-close>取消</button><button type="submit" class="button primary">启动 Agent ${icon("arrow", 15)}</button></footer></form></div>`;
  renderIncidentCards(document.querySelector("#dashboard-incidents"), state.scenarios);
  renderRuns(document.querySelector("#run-list"), state.runs.slice(0, 5));
  bindDashboardEvents();
}

function renderRuns(container, runs) {
  container.replaceChildren();
  if (!runs.length) {
    const empty = node("div", "run-empty");
    empty.innerHTML = `${icon("terminal", 21)}<strong>尚无 Agent Run</strong><p>从左侧真实事故中启动一次调查。</p>`;
    container.append(empty);
    return;
  }
  runs.forEach((run) => {
    const link = node("a", "run-item");
    link.href = `#/runs/${encodeURIComponent(run.run_id)}`;
    const dot = node("i", run.status);
    const copy = node("div", "");
    copy.append(node("strong", "", run.title), node("small", "", `${run.run_id} · ${formatDate(run.created_at)}`));
    const status = node("span", "", statusLabel(run.status));
    link.append(dot, copy, status);
    container.append(link);
  });
}

function bindDashboardEvents() {
  const modal = document.querySelector("#incident-modal");
  document.querySelector("#new-incident")?.addEventListener("click", () => { modal.hidden = false; });
  modal?.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => { modal.hidden = true; }));
  document.querySelector("#incident-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = event.currentTarget.querySelector('[type="submit"]');
    submit.disabled = true;
    submit.textContent = "Agent 运行中…";
    const data = new FormData(event.currentTarget);
    try {
      const run = await createRun({
        incident: {
          service: data.get("service"),
          severity: data.get("severity"),
          description: data.get("description"),
          environment: "production",
          signals: [],
          artifacts: [],
        },
      });
      location.hash = `#/runs/${run.run_id}`;
    } catch (error) {
      showToast(error.message, "error");
      submit.disabled = false;
      submit.innerHTML = `启动 Agent ${icon("arrow", 15)}`;
    }
  });
}

async function createRun(input) {
  const run = await api("/api/runs", {
    method: "POST",
    body: JSON.stringify({ ...input, session_id: state.sessionId }),
  });
  state.activeRun = run;
  state.runs = [run, ...state.runs.filter((item) => item.run_id !== run.run_id)];
  return run;
}

function renderWorkbench(scenario, run = null) {
  document.body.className = "page-workbench";
  const title = run?.title || scenario?.title || "Incident investigation";
  const service = run?.service || scenario?.request.service || "unknown-service";
  const severity = run?.severity || scenario?.request.severity || "UNKNOWN";
  const currentStatus = run?.status || scenario?.incident_status || "ready";
  app.innerHTML = `<div class="workbench-frame">${appSidebar("runs")}<div class="workbench-main">${appTopbar("Agent 工作台")}
    <main class="workbench-body">
      <section class="agent-canvas">
        <header><div><span class="canvas-eyebrow">INCIDENT GRAPH / ${run?.run_id || scenario?.source_incident_id || "NEW"}</span><h1>${run ? "Agent Run 执行图" : "准备启动事故调查"}</h1></div><div class="canvas-controls"><button>${icon("plus", 16)}</button><button>−</button><button>${icon("grid", 16)}</button></div></header>
        <div class="canvas-grid"><div class="graph-source"><span class="node-kicker">INCIDENT</span><div class="graph-icon">${icon("pulse", 21)}</div><strong id="graph-title"></strong><small id="graph-service"></small><i class="connector"></i></div><div class="graph-path" id="graph-path"></div></div>
        <footer><span>${icon("layers", 15)} Evidence graph</span><span>${icon("shield", 15)} Production writes disabled</span></footer>
      </section>
      <aside class="investigation-panel">
        <header class="panel-head"><div><span class="panel-agent-mark">OC</span><div><h2>OnCall Agent</h2><p>Evidence-grounded runtime</p></div></div><a href="#home" aria-label="关闭">${icon("x", 18)}</a></header>
        <nav class="panel-tabs"><button class="active">调查</button><button>证据</button><button>动作</button><button>边界</button></nav>
        <section class="incident-summary"><div class="summary-top"><span class="severity-badge ${severityClass(severity)}">${severity}</span><span class="run-state ${currentStatus}">${statusLabel(currentStatus)}</span></div><h3 id="panel-title"></h3><div class="summary-facts"><span>${icon("database", 14)} <b id="panel-service"></b></span><span>${icon("clock", 14)} ${formatDate(run?.created_at || scenario?.started_at)}</span></div>${(run?.source_url || scenario?.source_url) ? `<a class="source-link" href="${run?.source_url || scenario?.source_url}" target="_blank" rel="noopener noreferrer">查看原始事故 ${icon("external", 13)}</a>` : ""}</section>
        <div class="panel-scroll"><section class="agent-steps"><header><span>AGENT LOOP</span><small>${run ? `${run.tool_calls.length} tools` : "ready"}</small></header><div id="agent-steps"></div></section><section id="analysis-output"></section></div>
        <footer class="panel-actions" id="panel-actions"></footer>
      </aside>
    </main></div></div>`;
  document.querySelector("#graph-title").textContent = title;
  document.querySelector("#graph-service").textContent = `${service} · ${severity}`;
  document.querySelector("#panel-title").textContent = title;
  document.querySelector("#panel-service").textContent = service;
  if (run) renderRunDetails(run);
  else renderScenarioDetails(scenario);
}

function renderScenarioDetails(scenario) {
  const path = document.querySelector("#graph-path");
  ["Load incident", "Normalize", "Diagnose", "Validate", "Safety gate"].forEach((label, index) => {
    const item = node("div", `graph-tool pending tool-${index + 1}`);
    item.innerHTML = `<span>0${index + 1}</span><div><b>${label}</b><small>waiting</small></div><i></i>`;
    path.append(item);
  });
  const steps = document.querySelector("#agent-steps");
  scenario.request.signals.forEach((signal, index) => {
    const row = node("div", "timeline-row");
    row.innerHTML = `<span>${String(index + 1).padStart(2, "0")}</span><i></i>`;
    const copy = node("div", "");
    copy.append(node("strong", "", signal.name), node("p", "", signal.value), node("small", "", formatDate(signal.timestamp)));
    row.append(copy);
    steps.append(row);
  });
  const output = document.querySelector("#analysis-output");
  output.innerHTML = `<div class="ready-card"><span>${icon("activity", 20)}</span><div><strong>已加载真实事故时间线</strong><p>启动后，Agent 将执行五个只读工具阶段并生成可审计 Run。</p></div></div>`;
  const actions = document.querySelector("#panel-actions");
  const button = node("button", "run-agent-button");
  button.innerHTML = `${icon("pulse", 17)} 启动 OnCall Agent <span>→</span>`;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "正在执行 Agent Loop…";
    try {
      const run = await createRun({ scenario_key: scenario.key });
      location.hash = `#/runs/${run.run_id}`;
    } catch (error) {
      showToast(error.message, "error");
      button.disabled = false;
      button.innerHTML = `${icon("pulse", 17)} 重试 Agent Run <span>→</span>`;
    }
  });
  actions.append(button);
}

function renderRunDetails(run) {
  const path = document.querySelector("#graph-path");
  run.tool_calls.forEach((tool) => {
    const item = node("div", `graph-tool success tool-${tool.sequence}`);
    const seq = node("span", "", String(tool.sequence).padStart(2, "0"));
    const copy = node("div", "");
    copy.append(node("b", "", tool.tool), node("small", "", `${tool.duration_ms}ms · read-only`));
    const check = node("i", "");
    check.innerHTML = icon("check", 13);
    item.append(seq, copy, check);
    path.append(item);
  });
  const steps = document.querySelector("#agent-steps");
  run.tool_calls.forEach((tool) => {
    const row = node("div", "tool-row");
    const stateIcon = node("span", "tool-check");
    stateIcon.innerHTML = icon("check", 13);
    const copy = node("div", "");
    copy.append(node("strong", "", tool.tool), node("p", "", tool.output_summary));
    const time = node("small", "", `${tool.duration_ms}ms`);
    row.append(stateIcon, copy, time);
    steps.append(row);
  });

  const output = document.querySelector("#analysis-output");
  const primary = run.analysis.hypotheses[0];
  output.innerHTML = `<section class="analysis-card"><header><span>PRIMARY HYPOTHESIS</span><b>${Math.round(primary.confidence * 100)}%</b></header><h3></h3><p></p><div class="evidence-tags"></div></section><section class="action-card"><header><span>RECOMMENDED ACTION</span><b class="risk-chip ${run.analysis.recommendation.risk_level}">${run.analysis.recommendation.risk_level}</b></header><p></p><details><summary>验证与回滚</summary><div class="validation-list"></div><strong>Rollback</strong><p class="rollback"></p></details></section><section class="boundary-card"><span>${icon("shield", 17)}</span><p>公开实例仅记录审批决定，<b>不会执行</b>流量切换、回滚、Shell 或数据库写入。</p></section>`;
  output.querySelector(".analysis-card h3").textContent = primary.title;
  output.querySelector(".analysis-card > p").textContent = primary.rationale;
  const evidenceTags = output.querySelector(".evidence-tags");
  primary.supporting_evidence.forEach((id) => evidenceTags.append(node("span", "", id)));
  output.querySelector(".action-card > p").textContent = run.analysis.recommendation.action;
  const validation = output.querySelector(".validation-list");
  run.analysis.recommendation.validation.forEach((item) => {
    const row = node("p", ""); row.innerHTML = icon("check", 13); row.append(document.createTextNode(item)); validation.append(row);
  });
  output.querySelector(".rollback").textContent = run.analysis.recommendation.rollback;
  renderRunActions(run);
}

function renderRunActions(run) {
  const actions = document.querySelector("#panel-actions");
  actions.replaceChildren();
  if (run.status === "awaiting-approval") {
    const reject = node("button", "decision-button reject", "拒绝建议");
    const approve = node("button", "decision-button approve");
    approve.innerHTML = `${icon("shield", 15)} 批准为决策输入`;
    reject.addEventListener("click", () => decideRun(run, "reject"));
    approve.addEventListener("click", () => decideRun(run, "approve"));
    actions.append(reject, approve);
  } else {
    const summary = node("div", `decision-record ${run.status}`);
    summary.innerHTML = run.status === "approved" ? icon("check", 16) : run.status === "rejected" ? icon("x", 16) : icon("shield", 16);
    summary.append(document.createTextNode(`${statusLabel(run.status)} · 未执行生产动作`));
    actions.append(summary);
  }
}

async function decideRun(run, decision) {
  const buttons = document.querySelectorAll(".decision-button");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const updated = await api(`/api/runs/${encodeURIComponent(run.run_id)}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, operator: "web-demo-operator", note: "Decision recorded from public control plane" }),
    });
    state.activeRun = updated;
    state.runs = state.runs.map((item) => item.run_id === updated.run_id ? updated : item);
    showToast(decision === "approve" ? "已记录批准；未执行生产动作" : "已拒绝建议", "success");
    renderWorkbench(null, updated);
  } catch (error) {
    showToast(error.message, "error");
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function showToast(message, type = "info") {
  document.querySelector(".toast")?.remove();
  const toast = node("div", `toast ${type}`);
  toast.innerHTML = type === "error" ? icon("x", 15) : icon("check", 15);
  toast.append(document.createTextNode(message));
  document.body.append(toast);
  setTimeout(() => toast.remove(), 4200);
}

function renderKnowledgeMessages() {
  const container = document.querySelector("#knowledge-messages");
  if (!container) return;
  container.innerHTML = "";
  if (!state.chatMessages.length) {
    const welcome = node("div", "knowledge-message assistant");
    welcome.innerHTML = `<span class="message-avatar">AI</span><div><p>你好，我是 OnCall Knowledge Agent。你可以上传 PDF、Markdown 或 TXT 文档，然后基于知识库提问。</p></div>`;
    container.append(welcome);
    return;
  }
  state.chatMessages.forEach((message) => {
    const row = node("div", `knowledge-message ${message.role}`);
    const avatar = node("span", "message-avatar", message.role === "assistant" ? "AI" : "YOU");
    const body = node("div");
    body.append(node("p", "", message.content));
    if (message.citations?.length) {
      const citations = node("div", "message-citations");
      message.citations.forEach((citation) => {
        const chip = node("span", "", `${citation.citation_id} · ${citation.document_name}`);
        chip.title = citation.excerpt;
        citations.append(chip);
      });
      body.append(citations);
    }
    row.append(avatar, body);
    container.append(row);
  });
  container.scrollTop = container.scrollHeight;
}

function paintKnowledgeStatus() {
  const status = state.knowledgeStatus;
  if (!status) return;
  const values = {
    "#knowledge-document-count": `${status.document_count} 份`,
    "#knowledge-types": status.supported_types.join(" · "),
    "#knowledge-retriever": status.retriever,
    "#knowledge-storage": status.storage,
    "#memory-turns": `${Math.floor(state.chatMessages.length / 2)} 轮`,
    "#memory-session": state.sessionId.slice(0, 22),
  };
  Object.entries(values).forEach(([selector, value]) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  });
  const list = document.querySelector("#knowledge-document-list");
  if (!list) return;
  list.innerHTML = "";
  if (!state.knowledgeDocuments.length) {
    list.append(node("p", "knowledge-empty", "尚未上传文档"));
    return;
  }
  state.knowledgeDocuments.slice(0, 4).forEach((document) => {
    const row = node("div", "knowledge-document");
    const documentIcon = node("span", "document-icon");
    documentIcon.innerHTML = icon("database", 15);
    const copy = node("div");
    copy.append(node("strong", "", document.name), node("small", "", `${document.chunk_count} chunks · ${document.character_count} chars`));
    row.append(documentIcon, copy);
    list.append(row);
  });
}

function paintAgentTrace(trace = []) {
  const container = document.querySelector("#knowledge-trace");
  if (!container) return;
  container.innerHTML = "";
  const stages = trace.length ? trace : ["Intent Agent", "Retriever", "LLM Agent", "Guard", "Answer Ready"];
  stages.forEach((stage, index) => {
    const item = node("span", "", stage.includes(":") ? stage.split(":")[0] : stage);
    item.title = stage;
    container.append(item);
    if (index < stages.length - 1) container.append(node("i", "", "→"));
  });
}

async function loadKnowledgeWorkspace() {
  const [knowledgeStatus, knowledgeDocuments, chatMessages] = await Promise.all([
    api("/api/knowledge/status"),
    api("/api/knowledge/documents"),
    api(`/api/sessions/${encodeURIComponent(state.sessionId)}`),
  ]);
  Object.assign(state, { knowledgeStatus, knowledgeDocuments, chatMessages });
}

async function submitKnowledgeQuestion(form) {
  const input = form.querySelector("input[name='question']");
  const submit = form.querySelector("button[type='submit']");
  const question = input.value.trim();
  if (question.length < 2) return;
  state.chatMessages.push({ role: "user", content: question });
  renderKnowledgeMessages();
  input.value = "";
  submit.disabled = true;
  submit.textContent = "回答中…";
  try {
    const response = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question, session_id: state.sessionId, top_k: 4 }),
    });
    state.chatMessages.push({ role: "assistant", content: response.answer, citations: response.citations });
    state.chatTrace = response.trace;
    renderKnowledgeMessages();
    paintAgentTrace(response.trace);
    paintKnowledgeStatus();
  } catch (error) {
    state.chatMessages.push({ role: "assistant", content: `请求失败：${error.message}` });
    renderKnowledgeMessages();
  } finally {
    submit.disabled = false;
    submit.textContent = "发送 →";
    input.focus();
  }
}

async function uploadKnowledgeFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  const button = document.querySelector("#upload-knowledge-button");
  button.disabled = true;
  button.textContent = "正在解析文档…";
  const payload = new FormData();
  payload.append("file", file);
  try {
    await api("/api/knowledge/documents", { method: "POST", body: payload });
    const [knowledgeStatus, knowledgeDocuments] = await Promise.all([
      api("/api/knowledge/status"),
      api("/api/knowledge/documents"),
    ]);
    Object.assign(state, { knowledgeStatus, knowledgeDocuments });
    paintKnowledgeStatus();
    showToast(`${file.name} 已加入知识库`, "success");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    input.value = "";
    button.disabled = false;
    button.textContent = "上传知识库";
  }
}

async function renderCustomerService() {
  document.body.className = "page-knowledge";
  app.innerHTML = `<header class="knowledge-topbar"><div class="knowledge-topbar-inner"><a href="#landing">← 返回导航</a><div class="knowledge-brand"><span>OC</span><div><strong>OnCall Knowledge Agent</strong><small>Evidence-grounded RAG workspace</small></div></div><span class="runtime-pill"><i></i>Agent Runtime Online</span></div></header>
    <main class="knowledge-page shell-wide">
      <section class="knowledge-hero"><div><span>ONCALL AGENT PLAYGROUND</span><h1>让运行知识，<br/>真正被 Agent 理解</h1></div><div><p>上传事故手册、复盘报告或系统说明，通过检索增强生成（RAG）获得带来源的回答。</p><p>支持 PDF、Markdown、TXT 文档与有上限的会话记忆。</p></div></section>
      <section class="knowledge-layout">
        <article class="knowledge-chat-card">
          <header><div class="knowledge-agent-title"><span>AI</span><div><strong>OnCall Knowledge Agent</strong><small><i></i> Knowledge Base Online</small></div></div><b>RAG PLAYGROUND</b></header>
          <div class="knowledge-messages" id="knowledge-messages"></div>
          <section class="knowledge-trace-panel"><header><strong>AGENT TRACE</strong><span>READY</span></header><div id="knowledge-trace" class="knowledge-trace"></div></section>
          <section class="knowledge-composer"><h3>快捷示例</h3><div class="knowledge-prompts"><button>项目如何限制危险操作？</button><button>会话记忆如何工作？</button><button>知识库采用什么检索方式？</button></div><form id="knowledge-form"><input name="question" minlength="2" maxlength="4000" placeholder="输入知识库问题…" autocomplete="off" required><button type="submit">发送 →</button></form></section>
        </article>
        <aside class="knowledge-sidebar">
          <section class="knowledge-status-card"><header><h2>知识库状态</h2><span>已连接</span></header><div class="knowledge-banner"><strong>RAG</strong><small>Knowledge Base</small></div><div class="knowledge-stat-grid"><div><span>文档数量</span><strong id="knowledge-document-count">0 份</strong></div><div><span>文件类型</span><strong id="knowledge-types">PDF · MD</strong></div><div><span>Retriever</span><strong id="knowledge-retriever">Loading</strong></div><div><span>Storage</span><strong id="knowledge-storage">Loading</strong></div></div><div id="knowledge-document-list" class="knowledge-document-list"></div><input id="knowledge-file" type="file" accept=".pdf,.md,.markdown,.txt" hidden><button id="upload-knowledge-button" class="knowledge-upload">上传知识库</button><small class="upload-help">单文件最大 5 MB · 服务重启后清空</small></section>
          <section class="knowledge-memory-card"><header><h2>会话记忆</h2><span>MEMORY ON</span></header><dl><div><dt>Session ID</dt><dd id="memory-session">Loading</dd></div><div><dt>历史消息轮数</dt><dd id="memory-turns">0 轮</dd></div><div><dt>上下文窗口</dt><dd>最近 8 条消息</dd></div><div><dt>存储边界</dt><dd>Process-local</dd></div></dl><button id="clear-memory">清空本次会话</button></section>
        </aside>
      </section>
    </main>`;
  renderKnowledgeMessages();
  paintAgentTrace();
  document.querySelector("#knowledge-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitKnowledgeQuestion(event.currentTarget);
  });
  document.querySelectorAll(".knowledge-prompts button").forEach((button) => button.addEventListener("click", () => {
    const input = document.querySelector("#knowledge-form input");
    input.value = button.textContent;
    input.focus();
  }));
  document.querySelector("#upload-knowledge-button").addEventListener("click", () => document.querySelector("#knowledge-file").click());
  document.querySelector("#knowledge-file").addEventListener("change", (event) => uploadKnowledgeFile(event.currentTarget));
  document.querySelector("#clear-memory").addEventListener("click", async () => {
    await api(`/api/sessions/${encodeURIComponent(state.sessionId)}`, { method: "DELETE" });
    state.chatMessages = [];
    state.chatTrace = [];
    renderKnowledgeMessages();
    paintAgentTrace();
    paintKnowledgeStatus();
    showToast("本次会话已清空", "success");
  });
  try {
    await loadKnowledgeWorkspace();
    if (location.hash !== "#/customer-service") return;
    renderKnowledgeMessages();
    paintKnowledgeStatus();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function renderRunRoute(runId) {
  let run = state.runs.find((item) => item.run_id === runId) || state.activeRun;
  if (!run || run.run_id !== runId) {
    try { run = await api(`/api/runs/${encodeURIComponent(runId)}`); }
    catch (error) { showToast(error.message, "error"); location.hash = "#home"; return; }
  }
  state.activeRun = run;
  renderWorkbench(null, run);
}

function renderError() {
  document.body.className = "page-landing";
  app.innerHTML = `${landingHeader()}<main class="error-page"><span>CONNECTION ERROR</span><h1>无法连接 OnCall Runtime</h1><p></p><button class="button primary">重新连接</button></main>`;
  app.querySelector(".error-page p").textContent = state.error || "Unknown error";
  app.querySelector("button").addEventListener("click", () => { state.loading = true; renderLoading(); loadData(); });
}

function renderLoading() {
  document.body.className = "page-landing";
  app.innerHTML = `<div class="boot-screen"><span class="boot-mark">OC</span><div class="boot-line"><i></i></div><p>Connecting evidence runtime…</p></div>`;
}

function renderRoute() {
  if (state.loading) { renderLoading(); return; }
  if (state.error && !state.scenarios.length) { renderError(); return; }
  const hash = location.hash || "#landing";
  if (hash.startsWith("#/incidents/")) {
    const key = decodeURIComponent(hash.slice("#/incidents/".length));
    const scenario = state.scenarios.find((item) => item.key === key);
    if (scenario) renderWorkbench(scenario); else { showToast("事故不存在", "error"); location.hash = "#home"; }
    return;
  }
  if (hash.startsWith("#/runs/")) {
    const runId = decodeURIComponent(hash.slice("#/runs/".length));
    renderRunRoute(runId);
    return;
  }
  // Keep a human-readable playground route analogous to the referenced site.
  // It opens the latest sourced incident rather than a synthetic chat demo.
  if (hash === "#/customer-service") {
    renderCustomerService();
    return;
  }
  if (hash.startsWith("#home")) { renderDashboard(); return; }
  renderLanding();
}

window.addEventListener("hashchange", renderRoute);
window.addEventListener("DOMContentLoaded", () => {
  if (!location.hash) history.replaceState(null, "", "#landing");
  loadData();
});
