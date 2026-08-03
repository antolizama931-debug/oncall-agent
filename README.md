# OnCall Agent

## DeepSeek 配置（必需）

项目默认使用当前 DeepSeek V4 Flash 模型。旧模型名 `deepseek-chat` 和
`deepseek-reasoner` 已停用，不应继续配置。

首次运行前，在项目根目录执行：

```powershell
Copy-Item .env.example .env
notepad .env
```

将 `.env` 中的占位值替换为真实密钥：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

`.env` 已被 `.gitignore` 排除，禁止提交到 GitHub。密钥只由 FastAPI
后端读取，浏览器端不会获得密钥。未配置密钥或 DeepSeek 暂时不可用时，
界面会明确标记为 `Local fallback`，不会冒充模型结果。

公开部署前还应设置：

```dotenv
ONCALL_RATE_LIMIT_PER_MINUTE=5
ONCALL_DAILY_LIMIT=30
ONCALL_ALLOW_RULE_FALLBACK=true
```

当前公开输入支持事故描述，以及最多 5 个 `.txt`、`.log`、`.json` 或
`.md` 文件。文件总文本不得超过 40,000 字符。上传前必须删除密码、令牌、
个人信息和其他敏感数据。

面向公开演示和简历展示的事故响应智能体（Incident Response Agent）。系统将用户报告、指标、日志、链路追踪和变更事件转换为可审计证据，生成可验证的根因假设，并通过安全门控限制恢复建议。

## 当前能力

- 自由文本事故输入与三个合成事故场景；
- 证据、假设和恢复建议严格分层；
- 配置密钥后由 DeepSeek 生成结构化分析；未配置或服务异常时明确回退到本地确定性基线；
- 支持上传经过脱敏的日志、JSON、Markdown 和文本遥测文件；
- 证据不足时返回明确的不确定性，不编造根因；
- 所有生产写操作默认要求人工批准；
- FastAPI 自动 API 文档；
- 响应式公开展示页面；
- 请求限流、安全响应头、Docker 和自动化测试。

## 系统结构

```text
浏览器
  ├─ 首页、项目介绍、事故输入和执行轨迹
  └─ POST /api/analyze
          ↓
FastAPI
  ├─ Observe：规范化用户报告和遥测证据
  ├─ Correlate：关联信号与变更事件
  ├─ DeepSeek：只基于已编号证据生成结构化候选分析
  ├─ Validate：校验证据引用、字段结构和模型输出
  ├─ Diagnose：生成并排序可验证假设；异常时使用确定性基线
  └─ Gate：把建议映射为只读、需审批或禁止
```

## Windows 快速启动

双击 `run.bat`，或在 PowerShell 中运行：

```powershell
./run.ps1
```

然后打开：

- Web 界面：http://127.0.0.1:8000
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

## 手动启动

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Docker

```bash
docker compose up --build
```

## Render 公网部署

仓库根目录的 `render.yaml` 定义了 FastAPI Web Service、健康检查、新加坡区域、
公开演示限流和 DeepSeek 环境变量。导入 Blueprint 时，Render 会要求单独输入
`DEEPSEEK_API_KEY`；密钥不会进入 Git 仓库。

免费实例适合简历演示，但空闲 15 分钟后会休眠，首次访问可能需要约一分钟唤醒。
若需要稳定的面试演示延迟，应改用付费实例。

## 上线前配置

编辑 `frontend/config.js`：

```js
window.ONCALL_CONFIG = {
  ownerName: "你的姓名",
  repositoryUrl: "https://github.com/你的用户名/oncall-agent",
  resumeUrl: "你的简历地址",
};
```

## 安全边界

当前版本不会执行 Shell、数据库写入、流量切换或回滚操作。推荐措施只能作为人工决策输入。DeepSeek API 密钥仅由后端环境变量读取，不得写入 `frontend/`、Git 仓库或浏览器配置。上传的事故文本和文件会发送给 DeepSeek，公开演示前必须完成脱敏。

## 后续扩展

1. 增加 OpenTelemetry、Prometheus、Loki 或 Elasticsearch 只读连接器；
2. 增加匿名会话配额、验证码和成本监控，防止公开链接被滥用；
3. 使用历史事故建立检索增强生成（Retrieval-Augmented Generation, RAG）；
4. 对根因排序、证据引用率和修复建议安全性建立离线评测集；
5. 部署到支持 Python 后端的云平台并绑定独立域名。
