# InTheLoop 工作台与独立官网部署

两个域名使用两个 GitHub 仓库独立发布：

- `Geekpark-hub/jk-toolkit-intheloop`：内部运营工作台与 Python 后端，部署到 `toolkit-intheloop.geekpark.net`。
- `Geekpark-hub/intheloop`：只读中英文官网，部署到 `intheloop.geekpark.net`。

## 内容边界

工作台保存标签、文章、播客、英文稿与发布快照。独立官网不连接数据库，也不保存任何密码或 AI Key；它通过以下只读接口读取已经发布的资料：

```text
GET https://toolkit-intheloop.geekpark.net/api/v1/public/atlas/zh
GET https://toolkit-intheloop.geekpark.net/api/v1/public/atlas/en
```

未发布草稿、工作台登录、模型接口及第三方发布凭证不会出现在公开接口中。

## 工作台部署

1. 将 `.env.example` 复制为服务器 `.env`，只在服务器填写真实值。
2. 备份 `/data/toolkit.db`、`/data/toolkit-settings.json` 与持久卷。
3. `docker compose pull`
4. `docker compose up -d`
5. 将 `toolkit-intheloop.geekpark.net` 反向代理到 `127.0.0.1:3000`。

推送 `main` 后，GitHub Actions 构建：

```text
ghcr.io/geekpark-hub/jk-toolkit-intheloop/frontend:latest
ghcr.io/geekpark-hub/jk-toolkit-intheloop/backend:latest
```

## 独立官网部署

独立官网的部署文件与环境变量模板在 `Geekpark-hub/intheloop` 仓库中。公开站只需配置官网地址与上述只读 API 的地址。

## 环境变量原则

- `.env` 永远不提交 GitHub。
- `MODELINK_API_KEY`、微信、飞书和极客公园凭证只存在工作台服务器。
- 独立官网不需要模型 Key、管理密码或第三方凭证。
- GitHub Actions 使用仓库自带的 `GITHUB_TOKEN` 发布镜像，不需要把 Modelink Key 存进 GitHub。

## 回滚

分别回滚两个仓库对应的镜像标签。回滚工作台后端前先备份数据库；官网回滚不会修改内容数据。
