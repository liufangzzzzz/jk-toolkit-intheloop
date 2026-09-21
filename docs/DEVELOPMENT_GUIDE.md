# In The Loop 运营工作台开发交接文档

版本：2.1  
更新日期：2026-09-20  
用途：供后续开发、维护、部署和 Agent 接入人员使用。

## 1. 产品范围

这是一个纯内部运营工作台，没有外部展示页。登录后只有两个业务 Tab：

1. **公众号草稿**：读取公开飞书文档，生成 In The Loop 排版预览，并保存到微信公众号草稿箱。
2. **极客公园官网**：读取已发布微信文章或 Word 文件，自动处理正文、图片、标签和头图，然后保存为官网草稿或直接发布。

不在当前范围内的功能：

- 对外文章展示站
- 小宇宙或其他外部内容聚合
- 微信公众号视频自动上传
- 飞书私有文档授权登录
- 在浏览器中输入极客公园官网账号密码

## 2. 必须遵守的隔离原则

两个 Tab 必须保持业务独立。可以参考或复制已有实现，但不能通过互相引用业务代码来复用。

- 公众号接口只能使用 `/api/v1/wechat-draft/*`。
- 官网接口只能使用 `/api/v1/website-import/*`。
- Agent 官网接口只能使用 `/api/v1/agent/website/*`。
- 公众号后端归属 `backend/app/modules/wechat_draft/` 和 `backend/agents/intheloop/`。
- 官网后端归属 `backend/app/modules/website_ingest/`。
- `geekpark-sync`、`geekpark-word-uploader` 等旧插件仅可作为逻辑参考，运行时不得依赖它们。
- 一个 Tab 更新、替换或删除时，不应要求另一个 Tab 同时修改。
- 允许共享的只有通用基础设施：登录鉴权、数据库连接、设置存储、HTTP 代理和视觉基础样式。
- 禁止共享业务模型、解析状态、发布开关、第三方登录状态和发布服务函数。

如果两个模块需要相似逻辑，优先在各自目录中复制一份并独立维护。不要为了减少少量重复代码重新制造跨模块依赖。

## 3. 技术结构

```text
浏览器
  ↓
Next/Vinext 前端（3000）
  ↓ /api/* 同源代理
FastAPI 后端（8000，仅 Docker 内部访问）
  ├─ wechat_draft：飞书 → 微信草稿
  ├─ website_ingest：微信/Word → 极客公园官网
  ├─ auth：工作台登录
  ├─ settings_store：受保护配置
  └─ database：发布记录和 Agent 任务
```

主要技术：

- 前端：React 19、TypeScript、Vinext/Vite
- 后端：Python、FastAPI、Pydantic
- 数据：SQLite WAL
- 飞书公开文档：Playwright + `feishu-docx`
- Word：Mammoth；旧 `.doc` 先由 LibreOffice 转为 `.docx`
- 部署：Docker Compose + 宝塔 Nginx 反向代理

## 4. 关键目录

```text
app/ops/page.tsx                         两个 Tab 的前端交互
app/globals.css                          品牌样式与手机适配
app/api/[...path]/route.ts               前端到 FastAPI 的同源代理

backend/app/main.py                      FastAPI 入口
backend/app/auth.py                      登录、签名 Cookie
backend/app/database.py                  SQLite 初始化与迁移
backend/app/settings_store.py            服务端配置持久化

backend/app/modules/wechat_draft/        公众号 Tab 路由与服务
backend/agents/intheloop/                飞书解析、排版、微信上传

backend/app/modules/website_ingest/      官网 Tab 的完整独立实现
  assets.py                              临时图片存储
  models.py                              官网专用数据模型
  parser.py                              微信链接和 Word 解析
  publisher.py                           官网登录、图片上传、草稿/发布
  jobs.py                                Agent 幂等任务
  routes.py                              网页与 Agent API

backend/tests/                           后端自动化测试
docs/                                    部署和接口文档
scripts/local-preview.command            macOS 一键本地测试
compose.yaml                             宝塔 Docker 编排
```

## 5. 公众号草稿流程

### 输入

- 飞书新版文档 `/docx/` 链接
- 飞书知识库 `/wiki/` 链接
- 文档必须开启“互联网用户可阅读”
- 不需要飞书 App ID 或 App Secret

### 文档识别规则

- 标题：优先使用飞书文档标题。
- 作者：`作者：姓名`、`作者｜姓名`，或单独一行 `作者：` 后紧跟姓名。
- 编辑：`编辑：姓名`、`编辑｜姓名`，或单独一行 `编辑：` 后紧跟姓名。
- 摘要：`Why It Matters：内容`，或单独一行 `Why It Matters` 后紧跟摘要。
- 小标题：飞书标题 2/标题 3，或 `01 标题`、`1. 标题` 等编号标题。
- 图片：下载并缓存原图，预览和上传时使用缓存图片。
- 视频：只统计数量并给出简短提示，不进入公众号正文。

解析是确定性规则，不使用 AI 猜测字段。未命中的内容保留为普通正文。

### 输出

- In The Loop 固定 HTML 排版
- 标题、作者、编辑、摘要、标题层级和图片预览
- 微信公众号草稿 `media_id`
- 只创建草稿，不执行群发

### 主要接口

```text
GET  /api/v1/wechat-draft/settings
PUT  /api/v1/wechat-draft/settings
POST /api/v1/wechat-draft/settings/test
POST /api/v1/wechat-draft/parse
POST /api/v1/wechat-draft/publish
GET  /api/v1/wechat-draft/history
```

## 6. 极客公园官网流程

### 输入

- 已发布的 `https://mp.weixin.qq.com/...` 文章链接
- `.docx` 文件
- `.doc` 文件，最大 30MB

### 处理

1. 提取标题、摘要和正文 HTML。
2. 清理脚本、表单、iframe 和不允许的标签。
3. 下载正文图片到独立临时资产存储。
4. 优先提取公司名和人名，再补充主题词，最多建议 10 个标签。
5. 优先使用来源头图，否则使用正文第一张图片。
6. 发布前允许修改标题、摘要、标签和栏目。

当前实现补充：

- Word 支持拖拽、多选和逐篇审核；每篇完成后约 1.2 秒自动返回导入页，队列继续保留。
- Word 默认优先匹配标题为“行业资讯”的栏目；找不到标题时才回退到栏目 ID `2` 或服务器保存的默认栏目。
- 标签最多 10 个，公司名和人名排在主题词之前，便于官网 SEO。
- 预览正文可以直接进入编辑模式；完成编辑后恢复临时图片引用，发布端再次清洗 HTML。
- 颜色、背景色、文字加粗、对齐和合理图片尺寸会保留；脚本、远程样式和危险 CSS 仍会删除。
- 预览图片使用内嵌数据，不依赖 iframe 访问后端相对地址。
- 章节编号类方形小图在紧邻小标题时固定为 50px，避免铺满正文。
- 微信图片下载失败时显示图片序号、说明和原图链接；官网图片上传失败时保留本地副本下载入口。

### 输出模式

- `draft`：官网状态为 `unpublished`。
- `publish`：官网状态为 `published`，会立即上线。
- 直接发布不发送空的 `auto_publish_at`，避免后台出现 `Invalid date`。
- 官网鉴权使用查询参数，正文只发送旧插件已经验证过的最小发布字段。
- 发布成功的公开地址固定为 `https://www.geekpark.net/news/{文章ID}`；后台编辑地址单独返回。
- 每次请求使用唯一 `request_id`，防止重复创建。
- 官网登录过期时，在固定账号已配置的前提下自动重新登录一次。

### 主要接口

```text
GET  /api/v1/website-import/status
POST /api/v1/website-import/connect
POST /api/v1/website-import/parse-url
POST /api/v1/website-import/parse-file
GET  /api/v1/website-import/assets/{token}
POST /api/v1/website-import/publish
GET  /api/v1/website-import/history
```

## 7. Agent 官网接口

Agent 接口不使用网页 Cookie，通过请求头鉴权：

```http
X-Agent-Key: <ITL_AGENT_API_KEY>
```

接口：

```text
POST /api/v1/agent/website/import-url
POST /api/v1/agent/website/import-file
GET  /api/v1/agent/website/jobs/{job_id}
```

调用方必须提供稳定的 `idempotency_key`。重试时保持相同值，服务端将返回已有任务，避免重复发布。详细请求示例见 `docs/AGENT_API.md`。

## 8. 登录与安全

- 工作台密码：`TOOLKIT_INTHELOOP_PASSWORD`
- 会话签名：`ITL_SESSION_SECRET`
- Cookie：HttpOnly、SameSite=Lax；生产环境启用 Secure
- AppSecret、官网登录密码和 Agent Key 不得写入 Git、源码或部署压缩包
- 官网账号密码只允许从服务器 `.env` 读取
- 微信 AppSecret 可从 `.env` 读取，也可登录后保存在服务端配置文件
- 浏览器接口必须在后端校验登录，不能只依赖前端隐藏按钮
- Agent API 必须使用独立 Key，不能复用工作台密码

## 9. 服务器环境变量

正式部署至少需要：

```dotenv
TOOLKIT_INTHELOOP_PASSWORD=工作台登录密码
ITL_SESSION_SECRET=至少32字节随机值
NEXT_PUBLIC_SITE_ORIGIN=https://toolkit-intheloop.geekpark.net
ITL_ALLOWED_ORIGINS=https://toolkit-intheloop.geekpark.net
ITL_COOKIE_SECURE=true

WECHAT_APP_ID=wx0ad9c0e3d4f70a6c
WECHAT_APP_SECRET=公众号AppSecret
WECHAT_ACCOUNT_NAME=In The Loop.具身现场

GEEKPARK_LOGIN_NAME=官网登录账号
GEEKPARK_LOGIN_PASSWORD=官网登录密码
WEBSITE_GEEKPARK_API_BASE=https://mainssl.geekpark.net
WEBSITE_GEEKPARK_ADMIN_BASE=https://admin.geekpark.net
WEBSITE_GEEKPARK_PUBLIC_BASE=https://www.geekpark.net
WEBSITE_GEEKPARK_ROLES=dev

ITL_AGENT_API_KEY=独立随机密钥
ITL_DATABASE_PATH=/data/toolkit.db
ITL_SETTINGS_PATH=/data/toolkit-settings.json
ITL_IMPORT_ASSET_PATH=/data/import-assets
PUBLISHER_BACKEND_URL=http://backend:8000
```

完整可填写模板是单独交付的 `intheloop-server.env`。填写后由部署人员放到项目根目录并改名为 `.env`。

## 10. 本地开发

macOS 可双击：

```text
scripts/local-preview.command
```

或在终端运行：

```bash
./scripts/local-preview.command
```

脚本会安装缺失依赖、启动前后端并打开：

```text
http://localhost:3000
```

注意：

- `.docx` 本地可直接解析。
- `.doc` 本地需要 LibreOffice；Docker 镜像已内置。
- 飞书公开文档读取需要 Chromium 浏览器依赖和互联网访问。
- 真实微信连接要求本机或服务器的公网出口 IP 已加入公众号白名单。
- 没有外部账号凭证时，可以测试登录、布局、解析、预览、标签和头图，但不能验证真实草稿或发布。

## 11. 自动化检查

每次提交或交付前执行：

```bash
npm run lint
npm run build
PYTHONPATH=backend python -m pytest -q backend/tests
docker compose config
```

当前基线：

- 后端测试：34 项通过
- 前端 lint：通过
- 前端生产构建：通过
- Docker Compose 配置：通过
- 手机适配：390px 实测无横向溢出

## 12. 宝塔部署

1. 解压部署包到 `/www/wwwroot/toolkit-intheloop.geekpark.net/app`。
2. 将填写好的 `intheloop-server.env` 放进项目根目录并改名为 `.env`。
3. 在宝塔终端运行：

```bash
docker compose up -d --build
```

4. 宝塔反向代理指向 `http://127.0.0.1:3000`。
5. 为正式域名申请 HTTPS 证书，并开启强制 HTTPS。
6. 查询服务器公网出口 IPv4：

```bash
curl -4 https://api.ipify.org
```

7. 将输出 IP 加入微信公众号平台的 IP 白名单。

更新版本时：

```bash
docker compose up -d --build --force-recreate
```

不得覆盖服务器原有 `.env`，不得删除 Docker 数据卷。

## 13. 上线验收顺序

1. 使用服务器 `.env` 中的工作台密码登录。
2. 分别用电脑和手机打开，确认两个 Tab 可操作且无横向溢出。
3. 检测公众号连接。
4. 用包含标题、作者、Why It Matters、小标题、图片和视频的公开飞书测试稿解析。
5. 核对预览后保存微信草稿，在公众平台草稿箱确认结果。
6. 连接极客公园官网账号。
7. 分别测试微信链接、`.docx` 和 `.doc`。
8. 先保存官网草稿，核对正文、图片、标签、头图、作者和栏目。
9. 使用专门的测试稿验证一次“直接发布”。
10. 打开返回的 `/news/{文章ID}`，确认它是公开文章而不是后台预览，并确认后台列表日期有效。
11. 使用相同幂等键重复请求一次 Agent API，确认不会重复发布。

## 14. 已知限制

- 飞书视频目前只计数，不会自动上传微信或官网。
- 飞书私有文档和需要登录的链接无法读取。
- 飞书、微信或极客公园网页/API 改版后，相应解析或发布适配可能需要更新。
- 微信已发布文章可能触发平台访问验证，无法读取时应给用户明确错误，不要绕过平台验证。
- 临时图片过期后必须重新解析来源，不能继续使用旧预览发布。
- “直接发布”是真实线上操作，必须保留二次确认。

## 15. 后续修改检查表

- 是否只修改了目标 Tab 的业务模块？
- 是否意外引入了另一个 Tab 的服务函数或状态？
- 是否保持所有凭证只在服务端？
- 是否为写操作保留幂等键？
- 是否处理加载、空状态、失败、成功和重复提交？
- 是否在 390px 手机宽度复查按钮、表单、预览和长文本？
- 是否执行 lint、build、后端测试和 Compose 检查？
- 是否保留原 `.env` 和 Docker 数据卷的升级方式？
- 是否先测试草稿，再测试直接发布？

出现跨模块需求时，应通过稳定的 HTTP 数据契约协作，或在各模块中复制实现；不要恢复旧插件依赖，也不要让任一 Tab 成为另一个 Tab 的运行前提。
