# OnCall Agent

基于真实公开事故数据的证据约束型事故响应智能体（Incident Response Agent）。后端使用 FastAPI，将观察事实、根因假设和处置建议分层；所有生产写操作均被限制为人工审批或禁止。

**Railway 公网地址：** https://oncall-agent-production-4c9c.up.railway.app

## 产品界面

- `#landing`：产品落地页，展示运行边界、真实数据和五阶段执行模型。
- `#home`：事故控制台，浏览 GitHub、Cloudflare、Datadog 官方状态页事故、会话内运行记录和审批数量。
- `#/customer-service`：知识库 Agent 工作台，支持提问、文档上传、检索引用和会话记忆。
- `#/incidents/{scenario_key}`：深色调查工作台，可启动真实 Agent Run。
- `#/runs/{run_id}`：回放工具调用、证据、假设、建议和人工决策。

前端为无构建依赖的单页应用（Single-Page Application, SPA），与 FastAPI 同源部署。

## Agent 运行时

每次 `Agent Run` 会真实经过五个可审计阶段：

1. `statuspage.read` / `incident.input`：读取固定官方状态页或接收脱敏输入；
2. `evidence.normalize`：把观察事实与推测分开；
3. `diagnosis.rank`：生成并排序可验证假设；
4. `citations.validate`：校验证据引用；
5. `policy.gate`：根据风险决定完成、审批或阻断。

运行记录采用有上限的进程内存储（Process-local Store），服务重启后会清空。审批端点只记录操作员决定，`action_executed` 固定为 `false`，不会伪装成已连接生产系统。

主要 API：

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/scenarios` | 获取真实事故回放 |
| `GET` | `/api/dashboard` | 获取控制台汇总 |
| `POST` | `/api/runs` | 从场景或自定义事件启动 Agent Run |
| `GET` | `/api/runs/{run_id}` | 获取完整审计轨迹 |
| `POST` | `/api/runs/{run_id}/decision` | 记录批准或拒绝，不执行生产动作 |
| `POST` | `/api/knowledge/documents` | 上传并解析 PDF、Markdown 或 TXT |
| `GET` | `/api/knowledge/status` | 获取文档、分块和检索器状态 |
| `POST` | `/api/chat` | 执行检索增强问答并写入会话记忆 |
| `GET/DELETE` | `/api/sessions/{session_id}` | 读取或清空本次会话 |

## RAG 检索架构

- 数据库边界：项目没有使用 Milvus、Qdrant、Chroma 等独立向量数据库。上传文档的提取文本与元数据保存在 SQLite；BM25 倒排信息和 BGE 向量索引在应用进程内按启动数据重建。
- PDF 通过 `pypdf` 提取文本，Markdown/TXT 只按文本解析，不执行文档内指令。
- 多数据源：并行同步 GitHub、Cloudflare、Datadog 官方状态页真实事故，同时接收用户上传的 PDF、Markdown 和 TXT。
- 词法通道：BM25 召回故障码、服务名、命令和精确术语。
- 语义通道：FastEmbed 运行 `BAAI/bge-small-zh-v1.5` 中文稠密向量模型，召回措辞不同但语义相近的内容。
- 融合阶段：倒数排名融合（Reciprocal Rank Fusion, RRF）合并两路排名，避免直接相加量纲不同的 BM25 与余弦分数。
- 可审计流程：问题识别 → 数据源路由 → 混合检索 → RRF 融合 → DeepSeek 生成 → 安全校验 → 分层会话记忆。
- 单文件最大 5 MB，提取文本最多 250,000 字符。
- 用户上传文档的提取文本写入 `data/knowledge.db`（SQLite），原始 PDF 二进制不保存；分块和向量索引在启动时重建。
- Railway 默认文件系统在重部署时可能清空。只有将 `ONCALL_DATA_DIR` 指向 Railway Volume 挂载目录后，上传知识才能跨部署保留。
- 会话采用“滚动摘要 + 最近 8 条原文 + 12,000 字符硬预算”。会话仍保存在进程内存，服务重启后清空；摘要只维持上下文，不作为事实证据。
- DeepSeek 只能依据返回的知识片段生成回答；API 密钥仅存在服务端。

当前没有把系统标记为智能体式检索增强生成（Agentic RAG）。三个状态页与用户文档仍适合固定、可审计的检索工作流；加入自主工具规划和反复检索循环会增加时延、成本与失控面。只有在增加日志、指标、Trace、CMDB 等异构连接器，并建立可量化检索评测集后，才适合验证 Agentic RAG 是否带来收益。

## 数据来源

- 在线数据源：GitHub、Cloudflare、Datadog 的官方 Statuspage 公共接口。
- 在线模式：每个来源最多读取 12 条，共最多 36 条最近公开事故，并缓存 5 分钟。
- 部分降级：某一来源失败时保留其他在线来源；GitHub 失败时使用仓库内带事故 ID 和原始链接的验证快照。
- 回放边界：只向智能体提供事故时间线最早的 3 条公开更新，不把后续根因分析提前泄漏给模型。
- 来源展示：每个场景均返回 `source_name`、`source_url`、`source_incident_id`、`data_mode` 和 `fetched_at`。
- 中文展示：API 额外返回中文标题、中文结构化摘要和中文状态更新；英文原文继续保留，用于来源核对与证据审计。

这些数据只能证明相应厂商对外发布了事故信息，不能替代厂商内部日志、指标和链路追踪。模型输出是待验证假设，不是已证实根因。

## 本地运行

```powershell
Copy-Item .env.example .env
./run.ps1
```

- Web：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

未配置 `DEEPSEEK_API_KEY` 时，服务明确使用本地确定性回退，不会冒充模型结果。

## 环境变量

```dotenv
ONCALL_ENV=production
ONCALL_RATE_LIMIT_PER_MINUTE=5
ONCALL_DAILY_LIMIT=30
ONCALL_ALLOW_RULE_FALLBACK=true
ONCALL_STATUS_CACHE_SECONDS=300
ONCALL_STATUS_SCENARIO_LIMIT=6
ONCALL_MAX_RUNS=100
ONCALL_MAX_DOCUMENTS=20
ONCALL_MAX_SESSIONS=100
ONCALL_MAX_SESSION_MESSAGES=16
ONCALL_DENSE_MIN_SCORE=0.36

DEEPSEEK_API_KEY=你的服务端密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_MAX_TOKENS=2200
```

密钥只能配置在服务端环境变量中，不得写入 `frontend/` 或 Git。DeepSeek 官方在 2026-07-31 发布的 V4 Flash API 仍使用 `deepseek-v4-flash` 模型名。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖：真实事故映射、HTML 清理、来源追踪、上游失败快照回退、BM25 与 BGE 中文语义召回、RRF 状态、证据引用校验、危险建议阻断、Agent 五阶段轨迹、人工审批边界和 API 端到端流程。

## Railway 部署

仓库已包含 `Dockerfile` 与 `railway.json`：

- Dockerfile 监听 Railway 注入的 `PORT`；本地默认端口为 `8000`。
- 健康检查路径为 `/api/health`。
- 构建器固定为 Dockerfile。

从本目录部署：

```powershell
railway login
railway init
railway variables set ONCALL_ENV=production ONCALL_ALLOW_RULE_FALLBACK=true ONCALL_STATUS_CACHE_SECONDS=300 ONCALL_STATUS_SCENARIO_LIMIT=36 ONCALL_STATUS_PER_SOURCE_LIMIT=12 ONCALL_MAX_RUNS=100 ONCALL_MEMORY_RECENT_MESSAGES=8 ONCALL_MEMORY_SUMMARY_CHARS=2400 ONCALL_CONTEXT_MAX_CHARS=12000
railway variables set DEEPSEEK_API_KEY=你的密钥 DEEPSEEK_BASE_URL=https://api.deepseek.com DEEPSEEK_MODEL=deepseek-v4-flash DEEPSEEK_MAX_TOKENS=2200
railway up
railway domain
```

若通过本仓库连接 GitHub 部署，Railway 服务的 Root Directory 保持为空（仓库根目录）；平台会直接读取根目录下的 `Dockerfile` 与 `railway.json`。

如需让上传知识跨重部署保存，请先在 Railway 服务中创建并挂载 Volume（例如 `/data`），再设置 `ONCALL_DATA_DIR=/data`。Volume 是外部持久化资源，可能产生费用，因此仓库不会自动创建。

## GitHub Pages

`.github/workflows/pages.yml` 会把 `frontend/` 作为静态站点发布。前端通过
`frontend/config.js` 中的公开 Railway URL 请求后端，密钥不会进入 Pages。

发布要求：

1. 仓库默认分支为 `main`；
2. Repository Settings → Pages → Source 选择 `GitHub Actions`；
3. Railway CORS 只允许 localhost 与 `*.github.io`，不携带 Cookie 凭据；
4. 推送到 `main` 后查看 `Deploy frontend to GitHub Pages` 工作流。

## 安全边界

- 三个官方状态页 URL 均在后端固定，不接受用户提供的主机，避免服务端请求伪造（Server-Side Request Forgery, SSRF）。
- 外部状态文本在后端去除 HTML，前端使用 `textContent` 构建节点，避免跨站脚本（Cross-Site Scripting, XSS）。
- 上传内容会发送给已配置的 DeepSeek API；上传前必须删除密钥、令牌、个人信息和其他敏感数据。
- 公共应用不执行 Shell、数据库写入、流量切换或自动回滚。
