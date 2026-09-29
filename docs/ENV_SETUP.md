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
| 飞书应用 | `FEISHU_APP_ID`、`FEISHU_APP_SECRET` | 刷新飞书用户授权时填写；不会用机器人身份读取妙记 |
| 飞书用户授权 | `FEISHU_USER_REFRESH_TOKEN` | 读取你本人可见的私有妙记、或在你的云盘创建文档时填写 |
| 飞书导出文件夹 | `FEISHU_EXPORT_FOLDER_NAME`、`FEISHU_EXPORT_FOLDER_TOKEN` | 默认按名称查找个人云盘根目录下的“沟通记录”；只有重名或不在根目录时才填写 token |

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

修改服务器 `.env` 或更新 `compose.yaml` 后，需要重新创建容器，普通的 `restart` 不会重新读取环境变量：

```bash
docker compose pull
docker compose up -d --force-recreate
```

当前 `compose.yaml` 已显式传入 `.env.example` 中的全部工作台变量，包括 Modelink、飞书应用、飞书用户授权、微信与极客公园官网凭据。自动测试会检查两份文件，后续若新增变量却漏改 Compose，测试会直接失败。

音频整理会先尝试按「互联网用户可阅读」读取妙记；公开读取失败后，才使用 `FEISHU_USER_REFRESH_TOKEN` 对应的用户身份。它不会使用机器人的 `tenant_access_token` 读取妙记。原版直接保留妙记返回的说话人和时间轴。导出飞书文档也使用用户身份，并默认查找个人云盘根目录下名为“沟通记录”的文件夹。若该文件夹不在根目录，或根目录存在多个同名文件夹，请打开目标文件夹并从其链接中复制 folder token，填入 `FEISHU_EXPORT_FOLDER_TOKEN`。服务端应用还需开通读取云盘目录和创建、编辑 Docx 的权限。

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
