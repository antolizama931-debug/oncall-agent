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
    executing: "执行中",
    validating: "验证中",
    recovered: "已恢复",
    "rolled-back": "已回滚",
    escalated: "已升级人工",
  }[status] || status || "未知";
}

function dataModeLabel(mode) {
  return {
    live: "实时数据",
    "verified-snapshot": "已验证快照",
    "partial-live": "部分实时数据",
    "external-fallback": "外部资料降级",
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
    "github_status.read": "读取 Wikimedia Status 事故",
    "statuspage.read": "读取 Wikimedia 官方事故",
    "incident.input": "读取脱敏事故输入",
    "evidence.normalize": "规范化证据",
    "diagnosis.rank": "排序根因假设",
    "citations.validate": "校验证据引用",
    "policy.gate": "执行安全门控",
    "runbook.execute": "执行 Runbook 演练",
    "remediation.validate": "验证恢复结果",
    "knowledge.draft": "生成复盘候选",
    "telemetry.metrics.query": "查询企业指标",
    "telemetry.logs.search": "检索企业日志",
    "telemetry.traces.search": "查询链路追踪",
    "telemetry.changes.read": "读取最近变更",
  }[tool] || tool;
}

async function api(path, options = {}) {
  const { timeoutMs = 15000, ...fetchOptions } = options;
  const isForm = options.body instanceof FormData;
  const localHost = ["localhost", "127.0.0.1"].includes(location.hostname);
  const baseUrl = (localHost ? "" : (config.apiBaseUrl || "")).replace(/\/$/, "");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...fetchOptions,
      signal: controller.signal,
      headers: { ...(!isForm ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
    });
  } catch (error) {
    if (error.name === "AbortError") throw new Error("服务响应超时，请稍后重试");
    throw error;
  } finally {
    clearTimeout(timer);
  }
  let body = null;
  try { body = await response.json(); } catch (_) { body = null; }
  if (!response.ok) throw new Error(body?.detail || `请求失败（HTTP ${response.status}）`);
  return body;
}

async function loadData() {
  // 静态页面立即可用；远程数据渐进加载，任何单个接口都不能锁死首屏。
  state.loading = false;
  renderRoute();
  const [healthResult, runsResult] = await Promise.allSettled([
    api("/api/health", { timeoutMs: 10000 }),
    api(`/api/runs?session_id=${encodeURIComponent(state.sessionId)}`, { timeoutMs: 10000 }),
  ]);
  if (healthResult.status === "fulfilled") state.health = healthResult.value;
  if (runsResult.status === "fulfilled") state.runs = runsResult.value;

  const scenariosResult = await Promise.allSettled([api("/api/scenarios", { timeoutMs: 18000 })]);
  if (scenariosResult[0].status === "fulfilled") {
    state.scenarios = scenariosResult[0].value;
    state.error = null;
  } else {
    state.error = scenariosResult[0].reason?.message || "Wikimedia 事故数据暂不可用";
  }
  try { state.dashboard = await api("/api/dashboard", { timeoutMs: 12000 }); }
  catch (_) { state.dashboard = null; }
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
          <h1>让每一次故障，<span>都留下可验证的<br class="mobile-only-break"/>答案。</span></h1>
          <p>OnCall Agent 接收告警、聚合证据、定位已知故障，并通过受策略约束的 Runbook 完成处置、验证、回滚和知识沉淀。</p>
          <div class="hero-buttons"><a class="button primary" href="#home">进入事故控制台 ${icon("arrow", 16)}</a><a class="button secondary" href="#incidents">查看真实事故</a></div>
          <div class="hero-footnote"><span>${icon("shield", 15)} 公开站仅执行安全演练</span><span>${icon("link", 15)} 每个判断和动作可追溯</span></div>
        </div>
        <div class="hero-runtime" aria-label="OnCall Agent 执行预览">
          <div class="runtime-window">
            <div class="runtime-bar"><span><i></i><i></i><i></i></span><b>Agent 运行轨迹</b><small>实时</small></div>
            <div class="runtime-incident"><span class="severity-badge sev1">SEV-1</span><div><small>事故回放</small><strong>云服务性能下降</strong></div><span class="source-chip">官方状态页</span></div>
            <div class="agent-flow">
              <div class="flow-node active"><span>01</span><div><b>观察（Observe）</b><small>规范化公开信号</small></div><i></i></div>
              <div class="flow-line"></div>
              <div class="flow-node active"><span>02</span><div><b>诊断（Diagnose）</b><small>排序可验证根因</small></div><i></i></div>
              <div class="flow-line"></div>
              <div class="flow-node guarded"><span>03</span><div><b>处置与验证</b><small>审批 · 回滚 · 复盘</small></div><i></i></div>
            </div>
            <div class="runtime-result"><div><span>首要根因假设</span><strong>下游依赖服务性能下降</strong></div><b>74%</b></div>
          </div>
          <div class="floating-card card-source"><span>${icon("database", 17)}</span><div><b>真实数据源</b><small>Wikimedia 官方数据</small></div></div>
          <div class="floating-card card-policy"><span>${icon("shield", 17)}</span><div><b>策略门控</b><small>低风险自动化边界</small></div></div>
        </div>
      </section>

      <section class="proof-row shell">
        <div><strong>${state.dashboard?.incident_count ?? "—"}</strong><span>真实事故回放</span></div>
        <div><strong>${state.dashboard?.source_name || "Wikimedia"}</strong><span>主生产数据域</span></div>
        <div><strong>8</strong><span>端到端工具阶段</span></div>
        <div><strong>${state.dashboard?.recovered_count ?? 0}</strong><span>已验证闭环演练</span></div>
      </section>

      <section class="capability-section shell" id="capabilities">
        <div class="section-heading"><div><span>OnCall 控制平面</span><h2>从告警进入，<br/>到恢复验证结束。</h2></div><p>目标是自动处理高频、标准化、低风险且可回滚的告警；未知事故自动收集证据并升级人工。</p></div>
        <div class="capability-grid">
          <article class="cap-card violet"><div class="cap-icon">${icon("bell", 25)}</div><span>01 / 自动响应</span><h3>告警接收与去重</h3><p>受认证的 Webhook 接收企业告警，并按指纹去重；重复通知只更新发生次数，不重复启动调查。</p><footer>Alert → Incident ${icon("arrow", 15)}</footer></article>
          <article class="cap-card orange"><div class="cap-icon">${icon("layers", 25)}</div><span>02 / 诊断推理</span><h3>证据约束诊断</h3><p>模型只能引用已编号证据；缺少区分性遥测时，系统明确降低置信度并请求补充数据。</p><footer>证据优先 ${icon("arrow", 15)}</footer></article>
          <article class="cap-card blue"><div class="cap-icon">${icon("activity", 25)}</div><span>03 / 安全处置</span><h3>版本化 Runbook</h3><p>动作按风险分类；公开站只执行演练，企业连接器需要权限、审批、变更窗口和明确允许列表。</p><footer>策略约束执行 ${icon("arrow", 15)}</footer></article>
          <article class="cap-card green"><div class="cap-icon">${icon("shield", 25)}</div><span>04 / 恢复验证</span><h3>验证失败自动回滚</h3><p>每次处置绑定恢复条件。指标不满足时停止继续执行、演练回滚步骤并升级人工。</p><footer>验证后才能关闭 ${icon("arrow", 15)}</footer></article>
          <article class="cap-card rose"><div class="cap-icon">${icon("layers", 25)}</div><span>05 / 闭环沉淀</span><h3>待审核复盘候选</h3><p>自动整理证据、根因、动作和验证结果；审核通过后才允许进入正式知识库。</p><footer>越用越准，不污染知识库 ${icon("arrow", 15)}</footer></article>
        </div>
      </section>

      <section class="incident-section" id="incidents"><div class="shell">
        <div class="section-heading compact"><div><span>实时事故数据流</span><h2>从真实事故开始调查</h2></div><p>每条记录保留来源、事故 ID、时间线与数据新鲜度；原始事故正文保留来源语言，避免改变证据含义。</p></div>
        <div id="landing-incidents" class="landing-incidents"></div>
        <a class="wide-link" href="#home"><span>打开完整事故控制台</span>${icon("arrow", 18)}</a>
      </div></section>

      <section class="architecture-section shell" id="architecture">
        <div class="section-heading"><div><span>执行模型</span><h2>八个工具阶段，<br/>形成完整处置闭环。</h2></div><p>调查、授权、执行和知识发布相互分离。每个阶段都有输入、输出、状态和审计记录。</p></div>
        <div class="architecture-flow">
          ${["alert.receive","evidence.normalize","diagnosis.rank","citations.validate","policy.gate","runbook.execute","remediation.validate","knowledge.draft"].map((item, index) => `<div class="arch-node"><span>${String(index + 1).padStart(2, "0")}</span><b>${item}</b><small>${["接收去重","规范证据","排序假设","验证引用","风险决策","执行处置","验证回滚","复盘候选"][index]}</small></div>${index < 7 ? '<i>→</i>' : ''}`).join("")}
        </div>
      </section>

      <section class="landing-cta"><div><span>开始一次可审计调查</span><h2>把真实事故放进<br/>可审计的 Agent 循环。</h2><p>选择真实事故进入控制台，或使用混合检索 RAG 查询事故知识。</p><div class="cta-actions"><a class="button dark" href="#home">进入事故控制台 ${icon("arrow", 17)}</a><a class="button cta-secondary" href="#/customer-service">打开知识库 Agent</a></div></div></section>
    </main>
    <footer class="landing-footer shell"><div class="brand"><span class="brand-glyph">OC</span><span>OnCall Agent</span></div><p>证据约束型事故响应 · Railway 部署</p><a href="${config.repositoryUrl || "#"}" target="_blank" rel="noopener noreferrer">查看源代码 ${icon("external", 13)}</a></footer>`;
  renderIncidentCards(document.querySelector("#landing-incidents"), state.scenarios.slice(0, 3), true);
}

function incidentChineseSummary(scenario) {
  if (scenario.display_summary) return scenario.display_summary;
  const service = scenario.request.service || "相关服务";
  const updates = scenario.update_count || 0;
  const resolved = scenario.incident_status === "resolved";
  return `${service} ${resolved ? "曾发生公开服务异常，目前状态页显示已恢复" : "正在发生公开服务异常，仍需继续观察"}。状态页已发布 ${updates} 条更新，可进入调查页面核对完整时间线。`;
}

function incidentDisplayTitle(scenario) {
  return scenario?.display_title || "官方状态页公开服务异常";
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
    const titleBlock = node("div", "incident-title-block");
    const titleLabel = node("span", "incident-title-label", "事故标题（中文）");
    const title = node("h3", "", incidentDisplayTitle(scenario));
    const summary = node("p", "incident-summary-cn", incidentChineseSummary(scenario));
    titleBlock.append(titleLabel, title, summary);
    const original = document.createElement("details");
    original.className = "original-incident";
    const originalLabel = document.createElement("summary");
    originalLabel.textContent = "查看英文原文";
    original.append(
      originalLabel,
      node("strong", "", scenario.title),
      node("p", "", scenario.request.description),
    );
    titleBlock.append(original);
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
    article.append(meta, titleBlock, facts, footer);
    article.style.setProperty("--delay", `${index * 70}ms`);
    container.append(article);
  });
}

function appSidebar(active = "home") {
  return `<aside class="app-sidebar">
    <a class="sidebar-brand" href="#landing"><span>OC</span></a>
    <nav>
      <a class="${active === "home" ? "active" : ""}" href="#home" title="事故控制台">${icon("grid", 20)}<span>控制台</span></a>
      <a class="${active === "runs" ? "active" : ""}" href="#home#runs" title="Agent 运行记录">${icon("pulse", 20)}<span>运行记录</span></a>
      <a href="#landing#architecture" title="系统架构">${icon("layers", 20)}<span>执行架构</span></a>
    </nav>
    <div class="sidebar-bottom"><span class="sidebar-online"><i class="live-orb"></i>运行时在线</span><button title="当前会话">${icon("user", 18)}<span>当前会话</span></button></div>
  </aside>`;
}

function appTopbar(title = "事故控制台") {
  return `<header class="app-topbar">
    <div><button class="mobile-menu">${icon("menu", 18)}</button><a href="#landing">OnCall Agent</a><i>/</i><strong>${title}</strong></div>
    <div class="topbar-right"><span class="runtime-pill"><i></i>${dataModeLabel(state.dashboard?.data_mode || state.health?.incident_data_mode || "online")}</span><span class="avatar" title="演示操作员">操作</span></div>
  </header>`;
}

function renderDashboard() {
  document.body.className = "page-app";
  const investigationRuns = state.runs.filter((run) => ["analyzing", "blocked", "escalated"].includes(run.status));
  const approvalRuns = state.runs.filter((run) => ["awaiting-approval", "approved"].includes(run.status));
  const completedRuns = state.runs.filter((run) => ["completed", "recovered", "rolled-back", "rejected"].includes(run.status));
  app.innerHTML = `<div class="app-frame">${appSidebar("home")}<div class="app-main">${appTopbar("事故控制台")}
    <main class="dashboard shell-app">
      <section class="dashboard-heading"><div><span>自动响应、调查、审批与复盘</span><h1>事故处理中心</h1><p>先从待处理事故启动调查，再查看 Agent 聚合的证据和根因判断；任何处置建议都必须经过人工审批，完成后自动保存验证结果和复盘记录。</p></div><div class="dashboard-actions"><a class="button secondary" href="#/customer-service">向 Agent 提问</a><button class="button primary" id="new-incident">${icon("plus", 16)} 新建事故</button></div></section>
      <section class="console-notice"><span>${icon("shield", 18)}</span><div><strong>当前为安全演练环境</strong><p>事故数据来自 Wikimedia 官方公开状态页；系统不会连接或修改真实生产环境。接入企业监控和执行网关后，仍需使用权限控制、操作允许列表和人工审批。</p></div></section>
      <section class="metric-grid">
        <article><span>01 · 待处理事故</span><strong>${state.dashboard?.incident_count ?? state.scenarios.length}</strong><small>选择事故并启动 Agent 调查</small><i class="metric-icon purple">${icon("database", 20)}</i></article>
        <article><span>02 · Agent 调查</span><strong>${investigationRuns.length}</strong><small>收集证据、检索 Runbook、判断根因</small><i class="metric-icon orange">${icon("pulse", 20)}</i></article>
        <article><span>03 · 操作审批</span><strong>${approvalRuns.length}</strong><small>核对风险、验证条件和回滚方案</small><i class="metric-icon blue">${icon("shield", 20)}</i></article>
        <article><span>04 · 已完成事故</span><strong>${completedRuns.length}</strong><small>保存处置结果、恢复验证与复盘记录</small><i class="metric-icon green">${icon("check", 20)}</i></article>
      </section>
      <section class="dashboard-operations">
        <section class="panel incident-panel operation-panel operation-pending"><header><div><span>01 · 待处理事故</span><h2>公开事故待调查池</h2><small class="source-language-note">数据来自 ${state.dashboard?.source_name || "Wikimedia Status"}，用于验证调查流程，不代表你的企业正在发生这些事故。</small></div><span class="sync-label"><i></i>${dataModeLabel(state.dashboard?.data_mode || "loading")}</span></header><div id="dashboard-incidents" class="dashboard-incidents"></div></section>
        <section class="panel operation-panel" id="investigations"><header><div><span>02 · Agent 调查</span><h2>正在调查</h2><small>查看证据采集、知识检索和根因判断过程</small></div><span class="count-chip">${investigationRuns.length}</span></header><div id="investigation-list" class="operation-run-list"></div></section>
        <section class="panel operation-panel approval-panel" id="approvals"><header><div><span>03 · 操作审批</span><h2>等待人工决策</h2><small>批准前必须核对影响范围、风险、验证条件和回滚方案</small></div><span class="count-chip warning">${approvalRuns.length}</span></header><div id="approval-list" class="operation-run-list"></div></section>
        <section class="panel operation-panel" id="completed"><header><div><span>04 · 已完成事故</span><h2>验证与复盘记录</h2><small>包括无需处置、恢复成功、回滚、拒绝和升级人工处理的结果</small></div><span class="count-chip success">${completedRuns.length}</span></header><div id="completed-list" class="operation-run-list"></div></section>
      </section>
      <section class="runtime-strip"><div><span class="live-orb"></span><strong>Agent 运行正常</strong></div><dl><div><dt>模型</dt><dd>${state.health?.model || "未加载"}</dd></div><div><dt>告警入口</dt><dd>${state.health?.webhook_configured ? "Webhook 已连接" : "演示数据"}</dd></div><div><dt>遥测工具</dt><dd>${state.health?.tool_gateway_configured ? "企业网关已连接" : "未连接生产环境"}</dd></div><div><dt>执行模式</dt><dd>安全演练</dd></div></dl></section>
    </main></div></div>
    <div class="modal" id="incident-modal" hidden><div class="modal-backdrop" data-close></div><form class="modal-card" id="incident-form"><header><div><span>自定义事故输入</span><h2>新建脱敏调查</h2></div><button type="button" data-close aria-label="关闭">${icon("x", 18)}</button></header><p>提交事故描述和必要上下文。请勿上传密码、令牌、个人信息或生产机密。</p><label>服务名称<input name="service" maxlength="120" value="unknown-service" required></label><label>严重级别<select name="severity"><option>SEV-1</option><option selected>SEV-2</option><option>SEV-3</option><option value="UNKNOWN">未知</option></select></label><label>事故描述<textarea name="description" minlength="10" maxlength="6000" rows="7" placeholder="描述症状、影响范围、时间窗口和已有遥测……" required></textarea></label><footer><button type="button" class="button secondary" data-close>取消</button><button type="submit" class="button primary">启动 Agent ${icon("arrow", 15)}</button></footer></form></div>`;
  renderIncidentCards(document.querySelector("#dashboard-incidents"), state.scenarios);
  renderRuns(document.querySelector("#investigation-list"), investigationRuns, "暂无正在调查的事故", "从待处理事故中选择一条记录并启动 Agent。");
  renderRuns(document.querySelector("#approval-list"), approvalRuns, "暂无待审批操作", "只有匹配到标准 Runbook 且需要处置的调查才会进入这里。");
  renderRuns(document.querySelector("#completed-list"), completedRuns, "暂无已完成事故", "完成调查、验证或回滚后，记录会保存在这里。");
  bindDashboardEvents();
}

function renderRuns(container, runs, emptyTitle = "尚无 Agent 运行记录", emptyBody = "从真实事故列表中启动一次调查。") {
  container.replaceChildren();
  if (!runs.length) {
    const empty = node("div", "run-empty");
    empty.innerHTML = `${icon("terminal", 21)}<strong>${emptyTitle}</strong><p>${emptyBody}</p>`;
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
  const title = run?.display_title || scenario?.display_title || "事故调查";
  const service = run?.service || scenario?.request.service || "unknown-service";
  const severity = run?.severity || scenario?.request.severity || "UNKNOWN";
  const currentStatus = run?.status || scenario?.incident_status || "ready";
  app.innerHTML = `<div class="workbench-frame">${appSidebar("runs")}<div class="workbench-main">${appTopbar("Agent 工作台")}
    <main class="workbench-body">
      <section class="agent-canvas">
        <header><div><span class="canvas-eyebrow">事故执行图 / ${run?.run_id || scenario?.source_incident_id || "新建"}</span><h1>${run ? "Agent 运行执行图" : "准备启动事故调查"}</h1></div><div class="canvas-controls"><button title="放大">${icon("plus", 16)}</button><button title="缩小">−</button><button title="适应画布">${icon("grid", 16)}</button></div></header>
        <div class="canvas-grid"><div class="graph-source"><span class="node-kicker">事故输入</span><div class="graph-icon">${icon("pulse", 21)}</div><strong id="graph-title"></strong><small id="graph-service"></small><i class="connector"></i></div><div class="graph-path" id="graph-path"></div></div>
        <footer><span>${icon("layers", 15)} 端到端执行图</span><span>${icon("shield", 15)} 公开站仅执行安全演练</span></footer>
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
  ["读取事故", "规范化证据", "诊断根因", "校验引用", "安全门控", "执行处置", "恢复验证", "复盘候选"].forEach((label, index) => {
    const item = node("div", `graph-tool pending tool-${index + 1}`);
    item.innerHTML = `<span>0${index + 1}</span><div><b>${label}</b><small>等待执行</small></div><i></i>`;
    path.append(item);
  });
  const steps = document.querySelector("#agent-steps");
  scenario.request.signals.forEach((signal, index) => {
    const row = node("div", "timeline-row");
    row.innerHTML = `<span>${String(index + 1).padStart(2, "0")}</span><i></i>`;
    const copy = node("div", "");
    copy.append(
      node("strong", "", signal.display_name || "官方状态更新"),
      node("p", "", signal.display_value || "官方已发布新的事故进展。"),
      node("small", "", formatDate(signal.timestamp)),
    );
    const original = document.createElement("details");
    original.className = "timeline-original";
    const originalLabel = document.createElement("summary");
    originalLabel.textContent = "查看英文原文";
    original.append(originalLabel, node("p", "", `${signal.name}：${signal.value}`));
    copy.append(original);
    row.append(copy);
    steps.append(row);
  });
  const output = document.querySelector("#analysis-output");
  output.innerHTML = `<div class="ready-card"><span>${icon("activity", 20)}</span><div><strong>已加载真实事故时间线</strong><p>启动后，Agent 先执行五个只读调查阶段；批准 Runbook 后才进入处置演练、验证和复盘阶段。</p></div></div>`;
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
  path.classList.toggle("expanded", run.tool_calls.length > 5);
  run.tool_calls.forEach((tool) => {
    const item = node("div", `graph-tool ${tool.status === "failed" ? "failed" : "success"} tool-${tool.sequence}`);
    const seq = node("span", "", String(tool.sequence).padStart(2, "0"));
    const copy = node("div", "");
    copy.append(node("b", "", toolStageLabel(tool.tool)), node("small", "", `${tool.duration_ms} 毫秒 · ${tool.read_only ? "只读" : "演练写操作"}`));
    const check = node("i", "");
    check.innerHTML = icon(tool.status === "failed" ? "x" : "check", 13);
    item.append(seq, copy, check);
    path.append(item);
  });
  const steps = document.querySelector("#agent-steps");
  run.tool_calls.forEach((tool) => {
    const row = node("div", "tool-row");
    const stateIcon = node("span", `tool-check ${tool.status}`);
    stateIcon.innerHTML = icon(tool.status === "failed" ? "x" : "check", 13);
    const copy = node("div", "");
    copy.append(node("strong", "", toolStageLabel(tool.tool)), node("p", "", tool.output_summary));
    const time = node("small", "", `${tool.duration_ms}ms`);
    row.append(stateIcon, copy, time);
    steps.append(row);
  });

  const output = document.querySelector("#analysis-output");
  const primary = run.analysis.hypotheses[0];
  output.innerHTML = `<section class="analysis-card"><header><span>首要根因假设</span><b>${Math.round(primary.confidence * 100)}%</b></header><h3></h3><p></p><div class="evidence-tags"></div></section>
    <section class="action-card"><header><span>建议处置动作</span><b class="risk-chip ${run.analysis.recommendation.risk_level}">${riskLabel(run.analysis.recommendation.risk_level)}</b></header><p></p><details><summary>验证与回滚</summary><div class="validation-list"></div><strong>回滚方案</strong><p class="rollback"></p></details></section>
    ${run.runbook ? '<section class="runbook-card"><header><span>匹配的标准 Runbook</span><b>版本化</b></header><h3></h3><p class="runbook-meta"></p><ol class="runbook-steps"></ol><details><summary>恢复条件与回滚步骤</summary><div class="runbook-validation"></div><div class="runbook-rollback"></div></details></section>' : '<section class="boundary-card warning"><span></span><p>当前根因假设没有匹配到标准 Runbook，只能升级人工处理。</p></section>'}
    ${run.execution ? '<section class="execution-card"><header><span>处置与恢复验证</span><b></b></header><h3></h3><p class="execution-summary"></p><div class="execution-results"></div><p class="rollback-result"></p></section>' : ''}
    ${run.knowledge_candidate ? '<section class="knowledge-candidate-card"><header><span>事故知识候选</span><b></b></header><h3></h3><p class="candidate-summary"></p><dl><div><dt>候选根因</dt><dd class="candidate-cause"></dd></div><div><dt>验证结果</dt><dd class="candidate-validation"></dd></div></dl></section>' : ''}
    <section class="boundary-card"><span>${icon("shield", 17)}</span><p>当前公开实例使用<b>安全演练连接器</b>，不会连接企业生产权限；接入真实系统后仍必须使用允许列表、RBAC、审批和自动回滚。</p></section>`;
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

  if (run.runbook) {
    output.querySelector(".runbook-card h3").textContent = run.runbook.name;
    output.querySelector(".runbook-meta").textContent = `${run.runbook.runbook_id} · v${run.runbook.version} · 当前模式：安全演练 · 不允许自动执行`;
    const runbookSteps = output.querySelector(".runbook-steps");
    run.runbook.steps.forEach((step) => {
      const item = node("li", "");
      item.append(node("strong", "", step.description), node("small", "", step.mutating ? "需要写权限" : "只读检查"));
      runbookSteps.append(item);
    });
    run.runbook.validation_checks.forEach((text) => output.querySelector(".runbook-validation").append(node("p", "", `验证：${text}`)));
    run.runbook.rollback_steps.forEach((text) => output.querySelector(".runbook-rollback").append(node("p", "", `回滚：${text}`)));
  }

  if (run.execution) {
    const executionCard = output.querySelector(".execution-card");
    executionCard.classList.add(run.execution.status);
    executionCard.querySelector("header b").textContent = statusLabel(run.execution.status);
    executionCard.querySelector("h3").textContent = `${run.execution.connector} · ${run.execution.execution_id}`;
    executionCard.querySelector(".execution-summary").textContent = run.execution.validation_summary;
    run.execution.steps.forEach((step) => {
      const row = node("div", `execution-result ${step.status}`);
      row.append(node("span", "", String(step.sequence).padStart(2, "0")), node("strong", "", step.operation), node("p", "", step.output_summary));
      executionCard.querySelector(".execution-results").append(row);
    });
    if (run.execution.rollback_performed) executionCard.querySelector(".rollback-result").textContent = run.execution.rollback_summary;
  }

  if (run.knowledge_candidate) {
    const candidate = run.knowledge_candidate;
    const candidateCard = output.querySelector(".knowledge-candidate-card");
    candidateCard.querySelector("header b").textContent = { "pending-review": "待审核", accepted: "已接收", rejected: "已拒绝" }[candidate.status] || candidate.status;
    candidateCard.querySelector("h3").textContent = candidate.title;
    candidateCard.querySelector(".candidate-summary").textContent = candidate.summary;
    candidateCard.querySelector(".candidate-cause").textContent = candidate.root_cause;
    candidateCard.querySelector(".candidate-validation").textContent = candidate.validation_result;
  }
  renderRunActions(run);
}

function renderRunActions(run) {
  const actions = document.querySelector("#panel-actions");
  actions.replaceChildren();
  if (run.status === "awaiting-approval") {
    const reject = node("button", "decision-button reject", "拒绝建议");
    const approve = node("button", "decision-button approve");
    approve.innerHTML = `${icon("shield", 15)} 批准 Runbook`;
    reject.addEventListener("click", () => decideRun(run, "reject"));
    approve.addEventListener("click", () => decideRun(run, "approve"));
    actions.append(reject, approve);
  } else if (run.status === "approved") {
    const fail = node("button", "decision-button reject", "演练验证失败");
    const execute = node("button", "decision-button approve");
    execute.innerHTML = `${icon("activity", 15)} 执行成功演练`;
    fail.addEventListener("click", () => executeRun(run, "failure"));
    execute.addEventListener("click", () => executeRun(run, "success"));
    actions.append(fail, execute);
  } else if (run.knowledge_candidate?.status === "pending-review") {
    const reject = node("button", "decision-button reject", "拒绝知识候选");
    const accept = node("button", "decision-button approve");
    accept.innerHTML = `${icon("check", 15)} 审核并接收`;
    reject.addEventListener("click", () => reviewKnowledge(run, "reject"));
    accept.addEventListener("click", () => reviewKnowledge(run, "accept"));
    actions.append(reject, accept);
  } else {
    const summary = node("div", `decision-record ${run.status}`);
    summary.innerHTML = ["recovered", "completed"].includes(run.status) ? icon("check", 16) : run.status === "rejected" ? icon("x", 16) : icon("shield", 16);
    const knowledgeState = run.knowledge_candidate ? ` · 知识候选${run.knowledge_candidate.status === "accepted" ? "已接收" : "已审核"}` : "";
    summary.append(document.createTextNode(`${statusLabel(run.status)} · 未执行生产动作${knowledgeState}`));
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
    showToast(decision === "approve" ? "Runbook 已批准，可以进入安全演练" : "已拒绝建议", "success");
    renderWorkbench(null, updated);
  } catch (error) {
    showToast(error.message, "error");
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function executeRun(run, simulatedResult) {
  const buttons = document.querySelectorAll(".decision-button");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const updated = await api(`/api/runs/${encodeURIComponent(run.run_id)}/execute`, {
      method: "POST",
      body: JSON.stringify({
        operator: "web-demo-operator",
        confirmation: "EXECUTE DRY RUN",
        simulated_result: simulatedResult,
      }),
    });
    state.activeRun = updated;
    state.runs = state.runs.map((item) => item.run_id === updated.run_id ? updated : item);
    showToast(simulatedResult === "success" ? "处置演练通过恢复验证" : "恢复验证失败，已演练回滚并升级人工", simulatedResult === "success" ? "success" : "info");
    renderWorkbench(null, updated);
  } catch (error) {
    showToast(error.message, "error");
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function reviewKnowledge(run, decision) {
  const buttons = document.querySelectorAll(".decision-button");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const updated = await api(`/api/runs/${encodeURIComponent(run.run_id)}/knowledge-review`, {
      method: "POST",
      body: JSON.stringify({ decision, reviewer: "web-demo-reviewer" }),
    });
    state.activeRun = updated;
    state.runs = state.runs.map((item) => item.run_id === updated.run_id ? updated : item);
    showToast(decision === "accept" ? "知识候选已通过审核" : "知识候选已拒绝", "success");
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
    welcome.innerHTML = `<span class="message-avatar">AI</span><div><p>我是 OnCall 知识库 Agent。Wikimedia 事故、Runbook 和整改工单是主知识域；组件官方文档用于补充，其他企业事故仅作为低权重类比。你也可以上传 PDF、Markdown 或 TXT 文档。</p></div>`;
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
        const actionLabel = citation.applicable_for_action ? "可支持操作建议" : "仅供诊断参考";
        const chip = node("span", "", `${citation.citation_id} · ${citation.source_type || citation.document_name}`);
        chip.title = `${signalText}\n${citation.organization || "来源未知"} · 权威度 ${Math.round((citation.authority_level || 0) * 100)}% · ${actionLabel}\n${citation.document_name}\n${citation.excerpt}`;
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
  const namespaceLabels = {
    wikimedia_status: "Wikimedia 实时事故",
    wikimedia_incidents: "Wikimedia 事故复盘",
    wikimedia_runbooks: "Wikimedia Runbook",
    upstream_official_docs: "组件官方文档",
    external_postmortems: "外部事故类比",
    user_uploads: "用户上传",
  };
  const values = {
    "#knowledge-document-count": `${status.document_count} 份 / ${status.chunk_count} 个分块`,
    "#knowledge-types": status.namespaces?.length ? status.namespaces.map((item) => namespaceLabels[item] || item).join(" · ") : "等待数据",
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
    copy.append(node("strong", "", document.name), node("small", "", `${document.source_type} · ${document.organization} · 权威度 ${Math.round((document.authority_level || 0) * 100)}%`));
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
  // 页面先展示已有索引，再后台同步 Wikitech；同步慢或失败不影响提问和上传。
  api("/api/knowledge/sync", { method: "POST", timeoutMs: 30000 }).then(async (syncedStatus) => {
    state.knowledgeStatus = syncedStatus;
    state.knowledgeDocuments = await api("/api/knowledge/documents", { timeoutMs: 10000 });
    if (location.hash === "#/customer-service") paintKnowledgeStatus();
  }).catch((error) => {
    if (location.hash === "#/customer-service") showToast(`Wikimedia 知识同步未完成：${error.message}`, "error");
  });
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
      <section class="knowledge-hero"><div><span>OnCall Agent 知识工作台</span><h1>让运行知识，<br/>真正被 Agent 理解</h1></div><div><p>检索增强生成（RAG）以 Wikimedia 事故、Runbook 和工单为主域，回答保留原始来源、命名空间与权威等级。</p><p>检索链路：BM25 精确召回 + 多语言语义召回 + RRF 权威度重排；外部企业事故不能直接生成生产操作。</p></div></section>
      <section class="knowledge-layout">
        <article class="knowledge-chat-card">
          <header><div class="knowledge-agent-title"><span>AI</span><div><strong>OnCall 知识库 Agent</strong><small><i></i> 知识库在线</small></div></div><b>混合检索 RAG</b></header>
          <div class="knowledge-messages" id="knowledge-messages"></div>
          <section class="knowledge-trace-panel"><header><strong>RAG 执行轨迹</strong><span>准备就绪</span></header><div id="knowledge-trace" class="knowledge-trace"></div></section>
          <section class="knowledge-composer"><h3>快捷问题</h3><div class="knowledge-prompts"><button>Wikimedia 最近发生了哪些事故？</button><button>Wiki 编辑延迟应检查什么？</button><button>Wikimedia Runbook 如何限制危险操作？</button><button>外部事故资料何时会被使用？</button></div><form id="knowledge-form"><input name="question" minlength="2" maxlength="4000" placeholder="请输入要检索的知识库问题……" autocomplete="off" required><button type="submit">发送问题 →</button></form></section>
        </article>
        <aside class="knowledge-sidebar">
          <section class="knowledge-status-card"><header><h2>知识库状态</h2><span>分层数据域</span></header><div class="knowledge-banner"><strong>Hybrid RAG</strong><small>BM25 + Multilingual Embedding + RRF</small></div><div class="knowledge-stat-grid"><div><span>文档与分块</span><strong id="knowledge-document-count">正在加载</strong></div><div><span>数据来源</span><strong id="knowledge-types">正在加载</strong></div><div><span>检索器</span><strong id="knowledge-retriever">正在加载</strong></div><div><span>存储方式</span><strong id="knowledge-storage">正在加载</strong></div></div><div id="knowledge-document-list" class="knowledge-document-list"></div><input id="knowledge-file" type="file" accept=".pdf,.md,.markdown,.txt" hidden><button id="upload-knowledge-button" class="knowledge-upload">上传本地知识文档</button><small class="upload-help">Wikimedia 主域优先 · 外部事故仅供类比 · 支持 PDF、Markdown、TXT · 单文件最大 5 MB</small></section>
          <section class="knowledge-memory-card"><header><h2>会话记忆</h2><span>记忆已启用</span></header><dl><div><dt>会话 ID</dt><dd id="memory-session">正在创建</dd></div><div><dt>历史对话轮数</dt><dd id="memory-turns">0 轮</dd></div><div><dt>上下文策略</dt><dd>滚动摘要 + 最近 8 条</dd></div><div><dt>字符预算</dt><dd>最多 12,000 字符</dd></div><div><dt>存储边界</dt><dd>进程内存</dd></div></dl><button id="clear-memory">清空本次会话</button></section>
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
  // 后端冷启动或公开数据源超时不阻断静态导航页。
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
