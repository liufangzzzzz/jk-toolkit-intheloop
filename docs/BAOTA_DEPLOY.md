# 宝塔部署说明

建议域名：`toolkit-intheloop.geekpark.net`

## 1. 上传代码

建议目录：

```text
/www/wwwroot/toolkit-intheloop.geekpark.net/app
```

解压源码包后，在项目根目录复制环境变量模板：

```bash
cp .env.example .env
```

## 2. 设置密码和密钥

让部署人员编辑服务器上的 `.env`，不要把真实密码写进源码：

```dotenv
TOOLKIT_INTHELOOP_PASSWORD=团队登录工作台使用的密码
ITL_SESSION_SECRET=至少32位随机字符串
GEEKPARK_LOGIN_NAME=固定官网账号
GEEKPARK_LOGIN_PASSWORD=固定官网密码
ITL_AGENT_API_KEY=至少32位随机字符串
NEXT_PUBLIC_SITE_ORIGIN=https://toolkit-intheloop.geekpark.net
ITL_ALLOWED_ORIGINS=https://toolkit-intheloop.geekpark.net
```

`TOOLKIT_INTHELOOP_PASSWORD` 是网页登录密码。部署人员设置后，网页不会再出现首次创建密码流程。旧变量 `ITL_ACCESS_PASSWORD` 仍兼容，但新部署统一使用前者。

`.env` 不要放进以后发给别人的代码包。升级时保留服务器原有 `.env` 和 Docker 数据卷即可。

## 3. 启动

在项目目录执行：

```bash
docker compose up -d --build
```

前端只监听服务器本机 `127.0.0.1:3000`，Python 后端不直接暴露公网端口。SQLite 记录、临时导入图片和网页保存的公众号配置都在 Docker 数据卷中，重建容器不会丢失。

修改 `.env` 后需重新创建容器：

```bash
docker compose up -d --build --force-recreate
```

## 4. 宝塔反向代理

1. 在宝塔“网站”中新建域名站点。
2. 申请 Let's Encrypt 证书并开启强制 HTTPS。
3. 将反向代理目标设置为 `http://127.0.0.1:3000`。

也可以使用 `deploy/baota/nginx-location.conf` 中的配置。

## 5. 微信公众号 IP 白名单

先在宝塔终端查询这台服务器访问外网时使用的 IPv4：

```bash
curl -4 https://api.ipify.org
```

然后登录微信公众平台，在“设置与开发”下找到“基本配置”，编辑“IP 白名单”，把上一步得到的公网 IPv4 填进去并按平台要求确认。若服务器经过 NAT、代理或云厂商出口网关，应填写实际出口 IP，而不是内网 IP。

完成后登录运营工作台，在“公众号草稿”Tab 点击“检测连接”。如果返回 IP 不在白名单，重新核对实际出口 IP。

## 6. 上线验收

1. 使用 `.env` 中设置的管理密码登录。
2. 在公众号 Tab 保存 AppID / AppSecret，并检测连接。
3. 用一篇公开飞书测试稿解析预览，再写入微信草稿箱。
4. 在官网同步 Tab 检测固定官网账号连接。
5. 分别测试微信文章链接、`.docx` 和 `.doc`。
6. 多选两个 Word，确认系统逐篇进入审核，且 Word 默认栏目为“行业资讯”。
7. 先选择“保存草稿”核对正文、图片、颜色、标签、头图和栏目。
8. 用专门测试稿验证“直接发布”；该按钮会再次要求确认。
9. 打开返回的 `/news/{文章ID}`，确认是公开页，并确认官网后台日期不再显示 `Invalid date`。
10. 用错误的 Agent Key 请求一次接口，确认返回 `401`。

## 7. 更新源码

上传新版本时不要覆盖服务器 `.env`，不要删除 Docker 数据卷。然后运行：

```bash
docker compose up -d --build --force-recreate
```

数据库会自动升级。公众号配置、发布记录和官网登录状态会继续保留。
