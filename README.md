<div align="center">

# mistral2api

Mistral AI 批量注册 + API Key 自动创建 + OpenAI 兼容网关

纯 API · 零浏览器 · 无 Captcha

</div>

---

> [!IMPORTANT]
> 本项目仅用于自动化流程研究、测试环境验证和个人学习。使用者应自行遵守目标网站服务条款、当地法律法规和第三方服务限制。请勿用于滥用或未经授权的商业用途。

## 组件

| 文件 | 用途 |
|---|---|
| `register.py` | 批量注册 + API key 创建（CLI） |
| `server.py` | API 网关 — 多 key 轮询 + 429 冷却 + OpenAI 兼容 |
| `webui.py` | WebUI 管理面板 — key 池状态/注册/API 测试 |
| `ory_auth.py` | Ory Kratos 身份认证客户端 |
| `mail_client.py` | 临时邮箱客户端（兼容 cloudflare_temp_email API） |
| `mistral_api.py` | Mistral 原生 API 封装 |
| `proxy_pool.py` | 代理池轮换 + 健康检查 |
| `pending.py` | 断联恢复 — 状态持久化 |

## 架构

```
[WebUI :8083] ──管理──→ [Gateway :8082] ──轮询──→ [Mistral API]
                              ↑
[register.py] ──产 key──→ KeyPool (内存)
```

## 特性

- **纯 API 注册**：基于 Ory Kratos 身份系统，无需 Chromium / Selenium / Playwright
- **零 Captcha**：Mistral 注册流程无 Turnstile / hCaptcha / 手机验证
- **全自动闭环**：临时邮箱 → 注册 → 邮箱验证 → 两步登录 → 创建 API Key → 测试可用性
- **断联恢复**：每步写 pending.jsonl，中断后重跑自动检测未完成注册
- **并发注册**：ThreadPoolExecutor 多线程，`-w 4` 开 4 线程同时跑
- **代理池轮换**：支持多代理地址轮换，每个注册用不同出口 IP
- **网络重试**：每个 HTTP 请求自动重试 3 次，指数退避（1s→2s→4s）
- **批量支持**：一键批量注册，自动保存 Key
- **OpenAI 兼容**：产出的 Key 直接用于 `api.mistral.ai/v1/chat/completions`
- **依赖极简**：仅需 `requests`，无需浏览器和重量级依赖

## 与同类工具对比

| | grok-register | mistral2api |
|---|---|---|
| 浏览器 | Chromium + DrissionPage | **不需要** |
| Captcha | Turnstile（靠真实浏览器过） | **无** |
| 注册方式 | 页面模拟 | **纯 HTTP API** |
| 邮箱验证 | 页面填码 | **API 提取 + 自动验证** |
| 登录 | SSO cookie | **Ory 两步式 API 登录** |
| Key 获取 | grok2api 入池 | **admin API 直接创建** |
| 依赖 | 20+ 包 | **1 个（requests）** |

## 快速开始

### 环境要求

- Python 3.9+
- HTTP 代理（用于访问 mistral.ai）
- 自建临时邮箱服务（兼容 cloudflare_temp_email API）

### 安装

```bash
git clone https://github.com/SilenceSik/mistral2api.git
cd mistral2api
pip install -r requirements.txt
```

### 配置

复制配置文件并修改：

```bash
cp config.example.json config.json
```

```json
{
  "mail_api": "http://your-mail-server:8000",
  "mail_domains": ["your-domain-1.xyz", "your-domain-2.top"],
  "proxy": "http://127.0.0.1:7890",
  "proxy_pool": [],
  "password": "YourPassword123!",
  "register_count": 1,
  "delay": 2.0,
  "workers": 1,
  "max_retries": 3,
  "key_name": "auto-bot",
  "first_name": "Bot",
  "last_name": "User",
  "pending_file": "pending.jsonl"
}
```

### 运行

#### 1. 批量注册（CLI）

```bash
# 注册 1 个账号
python register.py -n 1

# 4 线程并发注册 20 个
python register.py -n 20 -w 4

# 恢复中断的注册
python register.py --resume
```

#### 2. 启动 API 网关

```bash
# 加载 key 文件启动
python server.py --port 8082 --load-keys accounts_latest.txt

# 带鉴权 + 代理
python server.py --port 8082 --api-keys sk-my-gw-key --proxy http://127.0.0.1:7890

# 客户端使用
curl http://localhost:8082/v1/chat/completions \
  -H "Authorization: Bearer sk-your-gw-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"mistral-small-latest","messages":[{"role":"user","content":"Hello"}]}'
```

#### 3. 启动 WebUI

```bash
python webui.py --port 8083 --gateway http://localhost:8082
# 浏览器打开 http://localhost:8083
```

### 输出

成功后自动保存到 `accounts_YYYYMMDD_HHMMSS.txt`：

```
email@your-domain.com|API_KEY_HERE
email2@your-domain.com|API_KEY_HERE
```

## 注册流程

```
创建临时邮箱
  → 初始化 Ory Kratos registration flow
  → 提交注册（email + password + name）
  → 触发验证码邮件（Ory verification flow）
  → 从邮箱 API 提取验证码
  → 提交验证码完成邮箱验证
  → 两步式登录（identifier_first → password）
  → 从 console RSC 数据提取 workspace UUID
  → POST admin.mistral.ai/api/billing/api-keys 创建 Key
  → 用新 Key 调 api.mistral.ai/v1/chat/completions 验证
```

## 技术细节

### Ory Kratos 身份系统

Mistral 使用 [Ory Kratos](https://www.ory.sh/kratos/) 作为身份管理系统：

- 注册：`POST /self-service/registration?flow=<id>`
- 验证：`POST /self-service/verification?flow=<id>`（method: code）
- 登录：两步式 — 先 `identifier_first`（提交邮箱），再 `password`
- CSRF：每个 flow 都有独立的 csrf_token，从 flow 详情中提取

### API Key 创建端点

```
POST https://admin.mistral.ai/api/billing/api-keys
Content-Type: application/json

{
  "name": "key-name",
  "workspace_uuid": "<from-console-RSC-data>",
  "primitive_access_scope": "shared_only"
}
```

Workspace UUID 从 `console.mistral.ai/api-keys` 的 RSC flight data 中提取。

### 临时邮箱

需要自建兼容 [cloudflare_temp_email](https://github.com/dreamhunter2333/cloudflare_temp_email) API 的邮箱服务：

- `POST /api/new_address` → `{address, jwt}`
- `POST /api/token` → `{data: {token}}`
- `GET /api/messages`（Bearer JWT）→ 邮件列表

邮箱服务端需支持 Catch-All 收信和通配符 DNS（`*.domain` MX 记录指向邮件服务器）。

### 邮箱格式

客户端自动生成仿真人邮箱地址：

```
{英文名}{姓氏}3ac{6位hex}@{2-3位随机前缀}.{域名}
```

示例：
- `aliceadams3ac7bc@my.example.xyz`
- `sarahwilson3ac849@r2.example.top`

## 可用模型

注册后可用的 55+ 模型包括：

| 模型 | 用途 |
|---|---|
| mistral-large-latest | 旗舰，复杂推理 |
| mistral-medium-latest | 平衡 |
| mistral-small-latest | 高性价比 |
| codestral-latest | 代码生成 |
| magistral-small-latest | 推理 |
| ministral-8b-latest | 轻量 |

## License

[MIT](LICENSE)
