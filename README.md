# OnCall Agent

基于真实公开事故数据的证据约束型事故响应智能体（Incident Response Agent）。后端使用 FastAPI，将观察事实、根因假设和处置建议分层；所有生产写操作均被限制为人工审批或禁止。

**Railway 公网地址：** https://oncall-agent-production-4c9c.up.railway.app

## 产品界面

- `#landing`：产品落地页，展示运行边界、真实数据和五阶段执行模型。
- `#home`：事故控制台，浏览 GitHub Status 事故、会话内运行记录和审批数量。
- `#/customer-service`：知识库 Agent 工作台，支持提问、文档上传、检索引用和会话记忆。
- `#/incidents/{scenario_key}`：深色调查工作台，可启动真实 Agent Run。
- `#/runs/{run_id}`：回放工具调用、证据、假设、建议和人工决策。

前端为无构建依赖的单页应用（Single-Page Application, SPA），与 FastAPI 同源部署。

## Agent 运行时

每次 `Agent Run` 会真实经过五个可审计阶段：

1. `github_status.read` / `incident.input`：读取固定数据源或接收脱敏输入；
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

## 知识库边界

- PDF 通过 `pypdf` 提取文本，Markdown/TXT 只按文本解析，不执行文档内指令。
- 检索器是明确标注的 BM25 风格词法检索，不冒充向量 Embedding。
- 单文件最大 5 MB，提取文本最多 250,000 字符。
- 文档、分块和会话均为进程内存储；Railway 重启后清空。
- DeepSeek 只能依据返回的知识片段生成回答；API 密钥仅存在服务端。

## 数据来源

- 主数据源：GitHub 官方状态页公共接口 `https://www.githubstatus.com/api/v2/incidents.json`。
- 在线模式：服务端获取最近公开事故，并缓存 5 分钟。
- 回退模式：使用仓库内保存的、带原始事故 ID 和链接的 2026-08-03 验证快照。
- 回放边界：只向智能体提供事故时间线最早的 3 条公开更新，不把后续根因分析提前泄漏给模型。
- 来源展示：每个场景均返回 `source_name`、`source_url`、`source_incident_id`、`data_mode` 和 `fetched_at`。

该数据只能证明 GitHub 对外发布了相应事故信息，不能替代 GitHub 内部日志、指标和链路追踪。模型输出是待验证假设，不是已证实根因。

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

测试覆盖：真实事故映射、HTML 清理、来源追踪、上游失败快照回退、证据引用校验、危险建议阻断、Agent 五阶段轨迹、人工审批边界和 API 端到端流程。

## Railway 部署

仓库已包含 `Dockerfile` 与 `railway.json`：

- Dockerfile 监听 Railway 注入的 `PORT`；本地默认端口为 `8000`。
- 健康检查路径为 `/api/health`。
- 构建器固定为 Dockerfile。

从本目录部署：

```powershell
railway login
railway init
railway variables set ONCALL_ENV=production ONCALL_ALLOW_RULE_FALLBACK=true ONCALL_STATUS_CACHE_SECONDS=300 ONCALL_STATUS_SCENARIO_LIMIT=6 ONCALL_MAX_RUNS=100
railway variables set DEEPSEEK_API_KEY=你的密钥 DEEPSEEK_BASE_URL=https://api.deepseek.com DEEPSEEK_MODEL=deepseek-v4-flash DEEPSEEK_MAX_TOKENS=2200
railway up
railway domain
```

若通过本仓库连接 GitHub 部署，Railway 服务的 Root Directory 保持为空（仓库根目录）；平台会直接读取根目录下的 `Dockerfile` 与 `railway.json`。

## GitHub Pages

`.github/workflows/pages.yml` 会把 `frontend/` 作为静态站点发布。前端通过
`frontend/config.js` 中的公开 Railway URL 请求后端，密钥不会进入 Pages。

发布要求：

1. 仓库默认分支为 `main`；
2. Repository Settings → Pages → Source 选择 `GitHub Actions`；
3. Railway CORS 只允许 localhost 与 `*.github.io`，不携带 Cookie 凭据；
4. 推送到 `main` 后查看 `Deploy frontend to GitHub Pages` 工作流。

## 安全边界

- GitHub Status URL 在后端固定，不接受用户提供的主机，避免服务端请求伪造（Server-Side Request Forgery, SSRF）。
- 外部状态文本在后端去除 HTML，前端使用 `textContent` 构建节点，避免跨站脚本（Cross-Site Scripting, XSS）。
- 上传内容会发送给已配置的 DeepSeek API；上传前必须删除密钥、令牌、个人信息和其他敏感数据。
- 公共应用不执行 Shell、数据库写入、流量切换或自动回滚。
