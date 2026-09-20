# Tab 与模块隔离约定

本项目是纯内部运营工作台，整个站点统一由 `intheloop` 管理密码保护，没有公开展示页。

## 当前 Tab

- `公众号草稿`：前端只调用 `/api/v1/wechat-draft/*`，后端代码位于 `backend/app/modules/wechat_draft/`。
- `官网同步`：前端只调用 `/api/v1/website-import/*`，后端代码位于 `backend/app/modules/website_ingest/`。
- Agent 官网接口：只调用 `/api/v1/agent/website/*`，使用独立 `ITL_AGENT_API_KEY`。

两个业务模块可以复制相同思路，但不能互相导入服务函数、配置或发布开关。修改一个 Tab 时，不应要求另一个 Tab 同时更新。

## 登录密码

网页管理密码使用：

```text
TOOLKIT_INTHELOOP_PASSWORD
```

旧变量 `ITL_ACCESS_PASSWORD` 仅为兼容保留。登录成功后服务端写入 HttpOnly 签名 Cookie。所有浏览器业务接口必须在后端校验登录状态，不能只依靠前端隐藏。

