const config = window.ONCALL_CONFIG || {};

let scenarios = {};
let activeScenario = "latency";
let currentRequest = null;
let inputMode = "example";
let artifacts = [];

const elements = {
  scenarioList: document.querySelector("#scenario-list"),
  description: document.querySelector("#incident-description"),
  service: document.querySelector("#incident-service"),
  severity: document.querySelector("#incident-severity"),
  incidentId: document.querySelector("#incident-id"),
  incidentTitle: document.querySelector("#incident-title"),
  trace: document.querySelector("#trace"),
  result: document.querySelector("#result-card"),
  runButton: document.querySelector("#run-analysis"),
  status: document.querySelector("#api-status"),
  modeExample: document.querySelector("#mode-example"),
  modeCustom: document.querySelector("#mode-custom"),
  files: document.querySelector("#incident-files"),
  artifactList: document.querySelector("#artifact-list"),
  provider: document.querySelector("#analysis-provider"),
};

function configureLinks() {
  const links = { repository: config.repositoryUrl, resume: config.resumeUrl };
  Object.entries(links).forEach(([key, url]) => {
    document.querySelectorAll(`[data-link="${key}"]`).forEach((element) => {
      if (url) {
        element.href = url;
        element.removeAttribute("aria-disabled");
        element.target = "_blank";
        element.rel = "noopener noreferrer";
      } else {
        element.addEventListener("click", (event) => event.preventDefault());
        element.title = `Set ${key} in frontend/config.js before publishing`;
      }
    });
  });
  if (config.ownerName) {
    document.querySelector("#owner-line").textContent = `Built by ${config.ownerName}.`;
  }
  document.querySelector("#year").textContent = new Date().getFullYear();
}

function setApiStatus(healthy, label) {
  elements.status.textContent = label;
  elements.status.parentElement.classList.toggle("offline", !healthy);
}

function clearResult() {
  elements.result.hidden = true;
  elements.trace.innerHTML = `
    <div class="trace-empty">
      <div class="empty-radar"><span></span><span></span><i></i></div>
      <strong>Ready to investigate</strong>
      <p>Choose a scenario or edit the report, then run the analysis.</p>
    </div>`;
}

function setInputMode(mode, { preserveFields = false } = {}) {
  inputMode = mode;
  elements.modeExample.classList.toggle("active", mode === "example");
  elements.modeCustom.classList.toggle("active", mode === "custom");
  elements.scenarioList.classList.toggle("disabled", mode === "custom");

  if (mode === "custom") {
    const preserved = preserveFields ? {
      description: elements.description.value,
      service: elements.service.value,
      severity: elements.severity.value,
    } : { description: "", service: "unknown-service", severity: "UNKNOWN" };
    currentRequest = {
      ...preserved,
      environment: "production",
      change_event: null,
      signals: [],
      artifacts: [],
    };
    if (!preserveFields) {
      elements.description.value = "";
      elements.service.value = "unknown-service";
      elements.severity.value = "UNKNOWN";
      artifacts = [];
      renderArtifacts();
    }
    document.querySelectorAll(".scenario").forEach((button) => {
      button.classList.remove("active");
      button.setAttribute("aria-selected", "false");
    });
    elements.incidentId.textContent = "CUSTOM";
    elements.incidentTitle.textContent = "Analyze your incident evidence";
    clearResult();
  } else {
    selectScenario(activeScenario);
  }
}

function selectScenario(key) {
  const scenario = scenarios[key];
  if (!scenario) return;
  activeScenario = key;
  inputMode = "example";
  elements.modeExample.classList.add("active");
  elements.modeCustom.classList.remove("active");
  elements.scenarioList.classList.remove("disabled");
  currentRequest = structuredClone(scenario.request);
  artifacts = structuredClone(currentRequest.artifacts || []);
  elements.description.value = currentRequest.description;
  elements.service.value = currentRequest.service;
  elements.severity.value = currentRequest.severity;
  renderArtifacts();
  elements.incidentId.textContent = "READY";
  elements.incidentTitle.textContent = scenario.title;
  document.querySelectorAll(".scenario").forEach((button) => {
    const selected = button.dataset.scenario === key;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
  });
  clearResult();
}

function renderScenarioButtons(items) {
  elements.scenarioList.innerHTML = items.map((scenario, index) => `
    <button class="scenario ${index === 0 ? "active" : ""}"
            data-scenario="${scenario.key}" role="option"
            aria-selected="${index === 0 ? "true" : "false"}">
      <span class="scenario-icon ${["orange", "purple", "blue"][index % 3]}">${index + 1}</span>
      <span><strong>${scenario.title}</strong><small>${scenario.subtitle}</small></span>
      <span class="scenario-arrow">›</span>
    </button>`).join("");
  document.querySelectorAll(".scenario").forEach((button) => {
    button.addEventListener("click", () => selectScenario(button.dataset.scenario));
  });
}

function collectRequest() {
  const base = currentRequest ? structuredClone(currentRequest) : { signals: [] };
  base.description = elements.description.value.trim();
  base.service = elements.service.value.trim() || "unknown-service";
  base.severity = elements.severity.value;
  base.artifacts = structuredClone(artifacts);
  if (inputMode === "custom") {
    base.change_event = null;
    base.signals = [];
  }
  return base;
}

function renderArtifacts() {
  elements.artifactList.innerHTML = "";
  artifacts.forEach((artifact, index) => {
    const item = document.createElement("div");
    item.className = "artifact-chip";
    const label = document.createElement("span");
    label.textContent = `${artifact.name} · ${artifact.content.length.toLocaleString()} chars`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${artifact.name}`);
    remove.addEventListener("click", () => {
      artifacts.splice(index, 1);
      renderArtifacts();
    });
    item.append(label, remove);
    elements.artifactList.append(item);
  });
}

async function loadArtifacts(fileList) {
  setInputMode("custom", { preserveFields: true });
  const selected = Array.from(fileList).slice(0, 5);
  const loaded = [];
  for (const file of selected) {
    const content = (await file.text()).slice(0, 20_000).trim();
    if (content) {
      loaded.push({
        name: file.name,
        content,
        media_type: file.type || "text/plain",
      });
    }
  }
  let total = 0;
  artifacts = loaded.filter((item) => {
    if (total + item.content.length > 40_000) return false;
    total += item.content.length;
    return true;
  });
  renderArtifacts();
}

function renderTrace(trace) {
  elements.trace.innerHTML = trace.map((step, index) => `
    <div class="trace-item">
      <span class="trace-index">${String(index + 1).padStart(2, "0")}</span>
      <span class="trace-stage">${step.stage}</span>
      <span class="trace-message">${step.message}</span>
      <span class="trace-time">${step.duration_ms}ms</span>
    </div>`).join("");
}

function renderResult(result) {
  const primary = result.hypotheses[0];
  document.querySelector("#result-hypothesis").textContent = primary.title;
  document.querySelector("#result-confidence").textContent = `${Math.round(primary.confidence * 100)}% confidence`;
  document.querySelector("#result-evidence").textContent = primary.rationale;
  document.querySelector("#result-action").textContent = result.recommendation.action;
  document.querySelector("#result-risk").textContent = result.recommendation.risk_level;
  const limitations = document.querySelector("#result-limitations");
  limitations.replaceChildren();
  result.limitations.forEach((item) => {
    const row = document.createElement("li");
    row.textContent = item;
    limitations.append(row);
  });
  const provider = result.analysis_mode === "deepseek"
    ? `DeepSeek · ${result.model}`
    : `Local fallback · ${result.analysis_mode}`;
  const usage = result.usage?.total_tokens ? ` · ${result.usage.total_tokens} tokens` : "";
  elements.provider.textContent = `${provider}${usage}`;
  elements.result.hidden = false;
  elements.incidentId.textContent = result.incident_id;
  elements.incidentTitle.textContent = result.summary;
}

async function runAnalysis() {
  const payload = collectRequest();
  if (payload.description.length < 10) {
    elements.description.focus();
    setApiStatus(false, "Add at least 10 characters");
    return;
  }

  elements.runButton.disabled = true;
  elements.runButton.textContent = "Analyzing…";
  elements.result.hidden = true;
  elements.trace.innerHTML = '<div class="trace-loading">Normalizing evidence and ranking hypotheses…</div>';

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Analysis request failed");
    renderTrace(body.trace);
    renderResult(body);
    setApiStatus(
      true,
      body.analysis_mode === "deepseek" ? `DeepSeek · ${body.model}` : "Local fallback",
    );
  } catch (error) {
    elements.trace.innerHTML = `<div class="trace-error"><strong>Analysis failed</strong><p>${error.message}</p></div>`;
    setApiStatus(false, "API unavailable");
  } finally {
    elements.runButton.disabled = false;
    elements.runButton.innerHTML = "<span>↻</span> Run analysis";
  }
}

function enableRevealAnimations() {
  const items = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) {
    items.forEach((item) => item.classList.add("visible"));
    return;
  }
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08 });
  items.forEach((item) => observer.observe(item));
}

async function initialize() {
  configureLinks();
  enableRevealAnimations();
  elements.runButton.addEventListener("click", runAnalysis);
  elements.modeExample.addEventListener("click", () => setInputMode("example"));
  elements.modeCustom.addEventListener("click", () => setInputMode("custom"));
  elements.files.addEventListener("change", () => loadArtifacts(elements.files.files));
  [elements.description, elements.service].forEach((field) => {
    field.addEventListener("input", () => {
      if (inputMode === "example") setInputMode("custom", { preserveFields: true });
    });
  });
  elements.severity.addEventListener("change", () => {
    if (inputMode === "example") setInputMode("custom", { preserveFields: true });
  });
  try {
    const [scenarioResponse, healthResponse] = await Promise.all([
      fetch("/api/scenarios"),
      fetch("/api/health"),
    ]);
    if (!scenarioResponse.ok || !healthResponse.ok) throw new Error("OnCall API unavailable");
    const items = await scenarioResponse.json();
    const health = await healthResponse.json();
    scenarios = Object.fromEntries(items.map((item) => [item.key, item]));
    renderScenarioButtons(items);
    selectScenario(items[0]?.key || "latency");
    setApiStatus(
      true,
      health.deepseek_configured ? `DeepSeek · ${health.model}` : "Local fallback",
    );
  } catch (error) {
    setApiStatus(false, "API unavailable");
    elements.scenarioList.innerHTML = `<p class="load-error">${error.message}</p>`;
  }
}

initialize();
