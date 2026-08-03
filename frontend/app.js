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
    ready: "准备就绪",
    analyzing: "分析中",
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

function dataModeLabel(mode) {
  return {
    live: "实时数据",
    "verified-snapshot": "已验证快照",
    "not-loaded": "等待加载",
    online: "在线",
    connecting: "连接中",
    loading: "加载中",
  }[mode] || mode || "状态未知";
}

function riskLabel(risk) {
  return {
    "read-only": "只读建议",
    "approval-required": "需要人工审批",
    blocked: "已阻断",
  }[risk] || risk || "风险未知";
}

function toolStageLabel(tool) {
  return {
    "github_status.read": "读取 GitHub Status 事故",
    "incident.input": "读取脱敏事故输入",
    "evidence.normalize": "规范化证据",
    "diagnosis.rank": "排序根因假设",
    "citations.validate": "校验证据引用",
    "policy.gate": "执行安全门控",
  }[tool] || tool;
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
  if (!response.ok) throw new Error(body?.detail || `请求失败（HTTP ${response.status}）`);
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
      <div class="header-actions"><span class="runtime-pill"><i></i>${dataModeLabel(state.dashboard?.data_mode || "connecting")}</span><a class="text-link" href="#home">打开事故控制台 ${icon("arrow", 14)}</a></div>
    </header>`;
}

function renderLanding() {
  document.body.className = "page-landing";
  app.innerHTML = `
    ${landingHeader()}
    <main>
      <section class="landing-hero shell">
        <div class="hero-copy">
          <span class="eyebrow"><i></i> 真实事故响应运行时</span>
          <h1>让每一次故障，<em>都留下可验证的答案。</em></h1>
          <p>OnCall Agent 从真实公开事故中提取证据，生成可证伪的根因假设，并在任何生产动作之前执行人工审批门控。</p>
          <div class="hero-buttons"><a class="button primary" href="#home">进入事故控制台 ${icon("arrow", 16)}</a><a class="button secondary" href="#incidents">查看真实事故</a></div>
          <div class="hero-footnote"><span>${icon("shield", 15)} 不执行生产写操作</span><span>${icon("link", 15)} 每条证据可追溯</span></div>
        </div>
        <div class="hero-runtime" aria-label="OnCall Agent 执行预览">
          <div class="runtime-window">
            <div class="runtime-bar"><span><i></i><i></i><i></i></span><b>Agent 运行轨迹</b><small>实时</small></div>
            <div class="runtime-incident"><span class="severity-badge sev1">SEV-1</span><div><small>事故回放</small><strong>GitHub 服务性能下降</strong></div><span class="source-chip">GitHub Status</span></div>
            <div class="agent-flow">
              <div class="flow-node active"><span>01</span><div><b>观察（Observe）</b><small>规范化公开信号</small></div><i></i></div>
              <div class="flow-line"></div>
              <div class="flow-node active"><span>02</span><div><b>诊断（Diagnose）</b><small>排序可验证根因</small></div><i></i></div>
              <div class="flow-line"></div>
              <div class="flow-node guarded"><span>03</span><div><b>安全门控</b><small>需要人工审批</small></div><i></i></div>
            </div>
            <div class="runtime-result"><div><span>首要根因假设</span><strong>下游依赖服务性能下降</strong></div><b>74%</b></div>
          </div>
          <div class="floating-card card-source"><span>${icon("database", 17)}</span><div><b>真实数据源</b><small>Statuspage API</small></div></div>
          <div class="floating-card card-policy"><span>${icon("shield", 17)}</span><div><b>策略门控</b><small>禁止自动修复</small></div></div>
        </div>
      </section>

      <section class="proof-row shell">
        <div><strong>${state.dashboard?.incident_count ?? "—"}</strong><span>真实事故回放</span></div>
        <div><strong>${state.dashboard?.source_name || "GitHub Status"}</strong><span>公开数据源</span></div>
        <div><strong>5</strong><span>可审计工具阶段</span></div>
        <div><strong>0</strong><span>自动生产写操作</span></div>
      </section>

      <section class="capability-section shell" id="capabilities">
        <div class="section-heading"><div><span>OnCall 控制平面</span><h2>不是普通聊天框，<br/>而是受约束的 Agent 运行时。</h2></div><p>观察、证据、假设、动作和授权严格分层。每个阶段都能被测试、回放和审计。</p></div>
        <div class="capability-grid">
          <article class="cap-card violet"><div class="cap-icon">${icon("database", 25)}</div><span>01 / 数据连接</span><h3>真实事故连接器</h3><p>服务端读取固定白名单 GitHub Status API，失败时回退到带来源链接的验证快照。</p><footer>实时读取与事故回放 ${icon("arrow", 15)}</footer></article>
          <article class="cap-card orange"><div class="cap-icon">${icon("layers", 25)}</div><span>02 / 诊断推理</span><h3>证据约束诊断</h3><p>模型只能引用已编号证据；缺少区分性遥测时，系统明确降低置信度并请求补充数据。</p><footer>证据优先 ${icon("arrow", 15)}</footer></article>
          <article class="cap-card blue"><div class="cap-icon">${icon("activity", 25)}</div><span>03 / 执行追踪</span><h3>完整执行轨迹</h3><p>工具调用、目的、输出摘要、时延和只读属性进入同一条 Agent Run，可直接检查。</p><footer>可观察执行循环 ${icon("arrow", 15)}</footer></article>
          <article class="cap-card green"><div class="cap-icon">${icon("shield", 25)}</div><span>04 / 安全治理</span><h3>人工审批门控</h3><p>置信度从不等于授权。高风险建议进入审批或阻断状态，公开实例不执行任何恢复操作。</p><footer>人工保留最终控制权 ${icon("arrow", 15)}</footer></article>
        </div>
      </section>

      <section class="incident-section" id="incidents"><div class="shell">
        <div class="section-heading compact"><div><span>实时事故数据流</span><h2>从真实事故开始调查</h2></div><p>每条记录保留来源、事故 ID、时间线与数据新鲜度；原始事故正文保留来源语言，避免改变证据含义。</p></div>
        <div id="landing-incidents" class="landing-incidents"></div>
        <a class="wide-link" href="#home"><span>打开完整事故控制台</span>${icon("arrow", 18)}</a>
      </div></section>

      <section class="architecture-section shell" id="architecture">
        <div class="section-heading"><div><span>执行模型</span><h2>五个工具阶段，<br/>一条可验证路径。</h2></div><p>Agent 运行不是隐藏的黑箱。每个工具只承担一个明确职责，并在最终建议前通过策略门控。</p></div>
        <div class="architecture-flow">
          ${["github_status.read","evidence.normalize","diagnosis.rank","citations.validate","policy.gate"].map((item, index) => `<div class="arch-node"><span>0${index + 1}</span><b>${item}</b><small>${["读取事故","规范证据","排序假设","验证引用","风险决策"][index]}</small></div>${index < 4 ? '<i>→</i>' : ''}`).join("")}
        </div>
      </section>

      <section class="landing-cta"><div><span>开始一次可审计调查</span><h2>把真实事故放进<br/>可审计的 Agent 循环。</h2><a class="button dark" href="#/customer-service">进入知识库 Agent ${icon("arrow", 17)}</a></div></section>
    </main>
    <footer class="landing-footer shell"><div class="brand"><span class="brand-glyph">OC</span><span>OnCall Agent</span></div><p>证据约束型事故响应 · Railway 部署</p><a href="${config.repositoryUrl || "#"}" target="_blank" rel="noopener noreferrer">查看源代码 ${icon("external", 13)}</a></footer>`;
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
    const source = node("span", "source-chip", dataModeLabel(scenario.data_mode));
    meta.append(severity, source);
    const title = node("h3", "", scenario.title);
    const description = node("p", "", scenario.request.description);
    const facts = node("div", "incident-facts");
    [scenario.request.service, `${scenario.update_count} 条公开更新`, formatDate(scenario.started_at)].forEach((text, factIndex) => {
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
      <a class="${active === "runs" ? "active" : ""}" href="#home#runs" title="Agent 运行记录">${icon("pulse", 20)}</a>
      <a href="#landing#architecture" title="系统架构">${icon("layers", 20)}</a>
    </nav>
    <div class="sidebar-bottom"><span class="live-orb" title="运行时在线"></span><button title="当前会话">${icon("user", 18)}</button></div>
  </aside>`;
}

function appTopbar(title = "事故控制台") {
  return `<header class="app-topbar">
    <div><button class="mobile-menu">${icon("menu", 18)}</button><a href="#landing">OnCall Agent</a><i>/</i><strong>${title}</strong></div>
    <div class="topbar-right"><span class="runtime-pill"><i></i>${dataModeLabel(state.dashboard?.data_mode || state.health?.incident_data_mode || "online")}</span><button title="搜索">${icon("search", 17)}</button><button title="通知">${icon("bell", 17)}</button><span class="avatar" title="演示操作员">操作</span></div>
  </header>`;
}

function renderDashboard() {
  document.body.className = "page-app";
  app.innerHTML = `<div class="app-frame">${appSidebar("home")}<div class="app-main">${appTopbar("事故控制台")}
    <main class="dashboard shell-app">
      <section class="dashboard-heading"><div><span>事故响应与运行审计</span><h1>事故控制台</h1><p>用于选择真实事故、启动一次受约束的 Agent 调查，并查看证据、根因假设、处置建议和人工审批记录。</p></div><button class="button primary" id="new-incident">${icon("plus", 16)} 新建调查</button></section>
      <section class="metric-grid">
        <article><span>真实事故</span><strong>${state.dashboard?.incident_count ?? state.scenarios.length}</strong><small>${state.dashboard?.source_name || "GitHub Status"} · ${dataModeLabel(state.dashboard?.data_mode || "—")}</small><i class="metric-icon purple">${icon("database", 20)}</i></article>
        <article><span>未解决事件</span><strong>${state.dashboard?.unresolved_count ?? 0}</strong><small>基于公开状态字段</small><i class="metric-icon orange">${icon("pulse", 20)}</i></article>
        <article><span>本次会话运行</span><strong>${state.runs.length}</strong><small>进程内审计记录</small><i class="metric-icon blue">${icon("terminal", 20)}</i></article>
        <article><span>待审批</span><strong>${state.runs.filter((run) => run.status === "awaiting-approval").length}</strong><small>不会自动执行动作</small><i class="metric-icon green">${icon("shield", 20)}</i></article>
      </section>
      <section class="dashboard-grid">
        <div class="panel incident-panel"><header><div><span>真实公开事故</span><h2>GitHub Status 事故流</h2><small class="source-language-note">原始事故标题和正文保留来源语言</small></div><span class="sync-label"><i></i>${dataModeLabel(state.dashboard?.data_mode || "loading")}</span></header><div id="dashboard-incidents" class="dashboard-incidents"></div></div>
        <aside class="dashboard-side">
          <section class="panel runtime-card"><header><div><span>运行时状态</span><h2>Agent 状态</h2></div><span class="healthy-chip">在线</span></header>
            <div class="runtime-brand"><span>OC</span><div><strong>${state.health?.model || "模型信息未加载"}</strong><small>${state.health?.deepseek_configured ? "大语言模型已配置" : "使用确定性降级分析"}</small></div></div>
            <dl><div><dt>证据连接器</dt><dd>GitHub Status</dd></div><div><dt>工具阶段</dt><dd>5 个</dd></div><div><dt>写操作权限</dt><dd>已禁用</dd></div><div><dt>运行记录</dt><dd>进程内存</dd></div></dl>
          </section>
          <section class="panel run-history" id="runs"><header><div><span>本次会话记录</span><h2>最近运行</h2></div><span>${state.runs.length}</span></header><div id="run-list"></div></section>
        </aside>
      </section>
    </main></div></div>
    <div class="modal" id="incident-modal" hidden><div class="modal-backdrop" data-close></div><form class="modal-card" id="incident-form"><header><div><span>自定义事故输入</span><h2>新建脱敏调查</h2></div><button type="button" data-close aria-label="关闭">${icon("x", 18)}</button></header><p>提交事故描述和必要上下文。请勿上传密码、令牌、个人信息或生产机密。</p><label>服务名称<input name="service" maxlength="120" value="unknown-service" required></label><label>严重级别<select name="severity"><option>SEV-1</option><option selected>SEV-2</option><option>SEV-3</option><option value="UNKNOWN">未知</option></select></label><label>事故描述<textarea name="description" minlength="10" maxlength="6000" rows="7" placeholder="描述症状、影响范围、时间窗口和已有遥测……" required></textarea></label><footer><button type="button" class="button secondary" data-close>取消</button><button type="submit" class="button primary">启动 Agent ${icon("arrow", 15)}</button></footer></form></div>`;
  renderIncidentCards(document.querySelector("#dashboard-incidents"), state.scenarios);
  renderRuns(document.querySelector("#run-list"), state.runs.slice(0, 5));
  bindDashboardEvents();
}

function renderRuns(container, runs) {
  container.replaceChildren();
  if (!runs.length) {
    const empty = node("div", "run-empty");
    empty.innerHTML = `${icon("terminal", 21)}<strong>尚无 Agent 运行记录</strong><p>从真实事故列表中启动一次调查。</p>`;
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
  const title = run?.title || scenario?.title || "事故调查";
  const service = run?.service || scenario?.request.service || "unknown-service";
  const severity = run?.severity || scenario?.request.severity || "UNKNOWN";
  const currentStatus = run?.status || scenario?.incident_status || "ready";
  app.innerHTML = `<div class="workbench-frame">${appSidebar("runs")}<div class="workbench-main">${appTopbar("Agent 工作台")}
    <main class="workbench-body">
      <section class="agent-canvas">
        <header><div><span class="canvas-eyebrow">事故执行图 / ${run?.run_id || scenario?.source_incident_id || "新建"}</span><h1>${run ? "Agent 运行执行图" : "准备启动事故调查"}</h1></div><div class="canvas-controls"><button title="放大">${icon("plus", 16)}</button><button title="缩小">−</button><button title="适应画布">${icon("grid", 16)}</button></div></header>
        <div class="canvas-grid"><div class="graph-source"><span class="node-kicker">事故输入</span><div class="graph-icon">${icon("pulse", 21)}</div><strong id="graph-title"></strong><small id="graph-service"></small><i class="connector"></i></div><div class="graph-path" id="graph-path"></div></div>
        <footer><span>${icon("layers", 15)} 证据执行图</span><span>${icon("shield", 15)} 生产写操作已禁用</span></footer>
      </section>
      <aside class="investigation-panel">
        <header class="panel-head"><div><span class="panel-agent-mark">OC</span><div><h2>OnCall Agent</h2><p>证据约束型运行时</p></div></div><a href="#home" aria-label="关闭">${icon("x", 18)}</a></header>
        <nav class="panel-tabs"><button class="active">调查</button><button>证据</button><button>动作</button><button>边界</button></nav>
        <section class="incident-summary"><div class="summary-top"><span class="severity-badge ${severityClass(severity)}">${severity}</span><span class="run-state ${currentStatus}">${statusLabel(currentStatus)}</span></div><h3 id="panel-title"></h3><div class="summary-facts"><span>${icon("database", 14)} <b id="panel-service"></b></span><span>${icon("clock", 14)} ${formatDate(run?.created_at || scenario?.started_at)}</span></div>${(run?.source_url || scenario?.source_url) ? `<a class="source-link" href="${run?.source_url || scenario?.source_url}" target="_blank" rel="noopener noreferrer">查看原始事故 ${icon("external", 13)}</a>` : ""}</section>
        <div class="panel-scroll"><section class="agent-steps"><header><span>Agent 执行循环</span><small>${run ? `${run.tool_calls.length} 个工具阶段` : "准备就绪"}</small></header><div id="agent-steps"></div></section><section id="analysis-output"></section></div>
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
  ["读取事故", "规范化证据", "诊断根因", "校验引用", "安全门控"].forEach((label, index) => {
    const item = node("div", `graph-tool pending tool-${index + 1}`);
    item.innerHTML = `<span>0${index + 1}</span><div><b>${label}</b><small>等待执行</small></div><i></i>`;
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
    copy.append(node("b", "", toolStageLabel(tool.tool)), node("small", "", `${tool.duration_ms} 毫秒 · 只读`));
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
    copy.append(node("strong", "", toolStageLabel(tool.tool)), node("p", "", tool.output_summary));
    const time = node("small", "", `${tool.duration_ms}ms`);
    row.append(stateIcon, copy, time);
    steps.append(row);
  });

  const output = document.querySelector("#analysis-output");
  const primary = run.analysis.hypotheses[0];
  output.innerHTML = `<section class="analysis-card"><header><span>首要根因假设</span><b>${Math.round(primary.confidence * 100)}%</b></header><h3></h3><p></p><div class="evidence-tags"></div></section><section class="action-card"><header><span>建议处置动作</span><b class="risk-chip ${run.analysis.recommendation.risk_level}">${riskLabel(run.analysis.recommendation.risk_level)}</b></header><p></p><details><summary>验证与回滚</summary><div class="validation-list"></div><strong>回滚方案</strong><p class="rollback"></p></details></section><section class="boundary-card"><span>${icon("shield", 17)}</span><p>公开实例仅记录审批决定，<b>不会执行</b>流量切换、回滚、Shell 或数据库写入。</p></section>`;
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
      body: JSON.stringify({ decision, operator: "web-demo-operator", note: "公开控制台记录的人工决定，未执行生产动作" }),
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
    welcome.innerHTML = `<span class="message-avatar">AI</span><div><p>我是 OnCall 知识库 Agent。系统已接入 GitHub Status 真实事故；你也可以上传 PDF、Markdown 或 TXT 文档。回答会同时使用 BM25 词法检索与 BGE 中文向量检索，并通过 RRF 融合结果。</p></div>`;
    container.append(welcome);
    return;
  }
  state.chatMessages.forEach((message) => {
    const row = node("div", `knowledge-message ${message.role}`);
    const avatar = node("span", "message-avatar", message.role === "assistant" ? "AI" : "用户");
    const body = node("div");
    body.append(node("p", "", message.content));
    if (message.citations?.length) {
      const citations = node("div", "message-citations");
      message.citations.forEach((citation) => {
        const signalText = citation.retrieval_signals?.join(" + ") || "检索命中";
        const chip = node("span", "", `${citation.citation_id} · ${citation.source_type || citation.document_name}`);
        chip.title = `${signalText}\n${citation.document_name}\n${citation.excerpt}`;
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
    "#knowledge-document-count": `${status.document_count} 份 / ${status.chunk_count} 个分块`,
    "#knowledge-types": status.source_types.length ? status.source_types.join(" · ") : "等待数据",
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
    copy.append(node("strong", "", document.name), node("small", "", `${document.source_type} · ${document.chunk_count} 个分块 · ${document.character_count} 个字符`));
    row.append(documentIcon, copy);
    list.append(row);
  });
}

function paintAgentTrace(trace = []) {
  const container = document.querySelector("#knowledge-trace");
  if (!container) return;
  container.innerHTML = "";
  const stages = trace.length ? trace : ["问题识别", "数据源路由", "混合检索", "RRF 融合", "答案生成", "安全校验"];
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
    button.textContent = "上传本地知识文档";
  }
}

async function renderCustomerService() {
  document.body.className = "page-knowledge";
  app.innerHTML = `<header class="knowledge-topbar"><div class="knowledge-topbar-inner"><a href="#landing">← 返回导航页</a><div class="knowledge-brand"><span>OC</span><div><strong>OnCall 知识库 Agent</strong><small>证据约束型 RAG 工作台</small></div></div><span class="runtime-pill"><i></i>Agent 运行时在线</span></div></header>
    <main class="knowledge-page shell-wide">
      <section class="knowledge-hero"><div><span>OnCall Agent 知识工作台</span><h1>让运行知识，<br/>真正被 Agent 理解</h1></div><div><p>检索增强生成（RAG）同时读取 GitHub Status 真实事故和用户上传文档，回答保留可核对来源。</p><p>检索链路：BM25 精确召回 + BGE 中文语义召回 + RRF 排名融合。支持 PDF、Markdown、TXT 和有上限的会话记忆。</p></div></section>
      <section class="knowledge-layout">
        <article class="knowledge-chat-card">
          <header><div class="knowledge-agent-title"><span>AI</span><div><strong>OnCall 知识库 Agent</strong><small><i></i> 知识库在线</small></div></div><b>混合检索 RAG</b></header>
          <div class="knowledge-messages" id="knowledge-messages"></div>
          <section class="knowledge-trace-panel"><header><strong>RAG 执行轨迹</strong><span>准备就绪</span></header><div id="knowledge-trace" class="knowledge-trace"></div></section>
          <section class="knowledge-composer"><h3>快捷问题</h3><div class="knowledge-prompts"><button>这个项目如何限制危险操作？</button><button>会话记忆如何工作？</button><button>混合检索采用了哪些技术？</button><button>最近的 GitHub 事故有哪些？</button></div><form id="knowledge-form"><input name="question" minlength="2" maxlength="4000" placeholder="请输入要检索的知识库问题……" autocomplete="off" required><button type="submit">发送问题 →</button></form></section>
        </article>
        <aside class="knowledge-sidebar">
          <section class="knowledge-status-card"><header><h2>知识库状态</h2><span>已连接</span></header><div class="knowledge-banner"><strong>Hybrid RAG</strong><small>BM25 + BGE + RRF</small></div><div class="knowledge-stat-grid"><div><span>文档与分块</span><strong id="knowledge-document-count">正在加载</strong></div><div><span>数据来源</span><strong id="knowledge-types">正在加载</strong></div><div><span>检索器</span><strong id="knowledge-retriever">正在加载</strong></div><div><span>存储方式</span><strong id="knowledge-storage">正在加载</strong></div></div><div id="knowledge-document-list" class="knowledge-document-list"></div><input id="knowledge-file" type="file" accept=".pdf,.md,.markdown,.txt" hidden><button id="upload-knowledge-button" class="knowledge-upload">上传本地知识文档</button><small class="upload-help">支持 PDF、Markdown、TXT · 单文件最大 5 MB · 服务重启后清空</small></section>
          <section class="knowledge-memory-card"><header><h2>会话记忆</h2><span>记忆已启用</span></header><dl><div><dt>会话 ID</dt><dd id="memory-session">正在创建</dd></div><div><dt>历史对话轮数</dt><dd id="memory-turns">0 轮</dd></div><div><dt>上下文窗口</dt><dd>最近 8 条消息</dd></div><div><dt>存储边界</dt><dd>进程内存</dd></div></dl><button id="clear-memory">清空本次会话</button></section>
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
  app.innerHTML = `${landingHeader()}<main class="error-page"><span>连接错误</span><h1>无法连接 OnCall Agent 运行时</h1><p></p><button class="button primary">重新连接</button></main>`;
  app.querySelector(".error-page p").textContent = state.error || "发生未知错误";
  app.querySelector("button").addEventListener("click", () => { state.loading = true; renderLoading(); loadData(); });
}

function renderLoading() {
  document.body.className = "page-landing";
  app.innerHTML = `<div class="boot-screen"><span class="boot-mark">OC</span><div class="boot-line"><i></i></div><p>正在连接证据运行时……</p></div>`;
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
