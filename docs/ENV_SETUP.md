# 环境变量怎么配置

环境变量就是只保存在服务器上的账号、密码和 API Key。它们不会写进网页，也不会提交到 GitHub。

## 你需要提供什么

部署人员只需向你收集下面几项，然后填入服务器的 `.env` 文件：

| 用途 | 变量 | 什么时候需要 |
| --- | --- | --- |
| 工作台登录 | `TOOLKIT_INTHELOOP_PASSWORD` | 必填；由你决定一个团队管理密码 |
| Modelink | `MODELINK_API_KEY` | 使用翻译、音频清洗、简版、纠错和生成稿件时填写 |
| 极客公园官网 | `GEEKPARK_LOGIN_NAME`、`GEEKPARK_LOGIN_PASSWORD` | 从工作台发布极客公园官网时填写 |
| 微信公众号 | `WECHAT_APP_SECRET` | 从工作台写入公众号草稿箱时填写；AppID 已预填，仍可修改 |
| 飞书应用 | `FEISHU_APP_ID`、`FEISHU_APP_SECRET` | 读取团队内私有妙记时填写 |
| 飞书用户授权 | `FEISHU_USER_REFRESH_TOKEN` | 导出一份你自己能看到的飞书文档时填写 |

`ITL_SESSION_SECRET` 和 `ITL_AGENT_API_KEY` 由部署人员生成随机值，你不需要自己想。公开的 In The Loop 官网不需要任何密码或 AI Key。

## 服务器怎么填

在工作台服务器的项目目录执行：

```bash
cp .env.example .env
```

然后只编辑 `.env`。最小可运行配置如下：

```dotenv
TOOLKIT_INTHELOOP_PASSWORD=你选择的团队管理密码
ITL_SESSION_SECRET=部署人员生成的长随机值
ITL_AGENT_API_KEY=部署人员生成的长随机值
MODELINK_API_KEY=你之后提供的ModelinkKey
```

AI Key 尚未填写时，网站和工作台仍能打开；涉及模型的按钮会明确显示“未配置”。你填好 Key 并重启服务后，四个工作流共用同一个 Modelink 接口，界面会要求每次操作明确选择模型。

独立官网服务器只需：

```dotenv
ITL_PUBLIC_ORIGIN=https://intheloop.geekpark.net
INTHELOOP_CONTENT_API_ORIGIN=https://toolkit-intheloop.geekpark.net
```

## 不要这样做

- 不要把真实 Key、账号或密码发到 GitHub Issue、代码文件或群聊截图里。
- 不要修改 `.env.example` 来填写真实值；它只是字段说明。
- 不要把工作台的 `.env` 复制到公开官网仓库。

服务器上的 `.env` 已被 Git 忽略，不会随 `git push` 上传。
