# In The Loop 运营工作台

仅供内部使用的统一内容运营工具。前后端、AI 网关和发布模块都包含在本项目内；公开中英文官网位于独立仓库 `Geekpark-hub/intheloop`。

## 四个工作流

### 公众号草稿

- 保存并检测微信公众号 AppID / AppSecret
- 读取「互联网用户可阅读」的飞书文档
- 识别标题、作者、编辑、Why It Matters、标题层级、图片和视频数量
- 下载飞书正文图片、生成公众号预览并写入微信公众号草稿箱
- 视频只计数和提示，暂不自动上传到公众号

### 官网同步

- 从已发布的 `mp.weixin.qq.com` 文章导入正文和图片
- 拖拽或多选 `.docx` / `.doc`，解析后逐篇审核
- 自动优先建议公司名、人名和主题标签，Word 默认选择“行业资讯”栏目
- 保留安全的正文颜色和图片尺寸，以第一张可用图片作为头图
- 发布前可修改标题、摘要、标签、栏目，并可直接修改预览正文
- 图片失败时显示具体序号、原因和原图/本地下载入口
- 可保存官网草稿，也可二次确认后直接发布
- 官网账号密码只从服务器环境变量读取，不在浏览器中输入
- 提供带 API Key 和幂等键的独立 Agent API

### InTheLoop 独立站

- 粘贴微信、官网或播客链接并整理中英文版本
- 维护统一的大、中、小三级标签库和地图展示层级
- 中文保留原链接，英文正文发布到独立官网
- 独立官网只读取已发布快照，不读取草稿或管理配置

### 音频整理

- 读取文本、字幕、飞书妙记、YouTube、Bilibili 与音频素材
- 生成原版、清洗版和简版，并支持自然语言纠错
- 稿件单独基于清洗版生成
- 可复制结果或以用户身份导出飞书文档

## 本机测试

在 Finder 中双击 `scripts/local-preview.command`，或在终端运行：

```bash
./scripts/local-preview.command
```

脚本会启动前后端并打开 `http://localhost:3000`。首次打开可在网页设置管理密码；生产环境建议由部署人员在 `.env` 设置。

本机读取 `.doc` 需要安装 LibreOffice；`.docx` 不需要。Docker 宝塔版本已经内置 LibreOffice Writer。

### 不连接真实账号也能检查

1. 登录后切换四个 Tab，确认手机和电脑布局。
2. 在“公众号草稿”中粘贴互联网用户可阅读的飞书链接，检查标题、作者、Why It Matters、图片和全文预览。
3. 在“极客公园官网”中上传 `.docx`，检查正文、自动标签、头图和栏目。
   可一次选择多个 Word，系统每次打开一篇供审核；完成后自动回到队列。
4. 账号未连接时，保存与发布按钮会保持禁用，不会误写入线上系统。

### 本机连接真实账号

- 微信公众号：可直接在网页填写 AppID / AppSecret 并检测连接。本机当前的公网出口 IP 也必须加入公众号 IP 白名单。点击“保存到微信草稿箱”会真的创建草稿，但不会直接群发。
- 极客公园官网：先把 `GEEKPARK_LOGIN_NAME` 和 `GEEKPARK_LOGIN_PASSWORD` 写入项目根目录的 `.env`，重启脚本，再点击“连接官网”。建议先只测试“保存草稿”；“直接发布”会把文章立即发布到官网。
- 飞书公开文档读取不需要飞书 App ID 或 Secret，但文档必须允许互联网用户访问。

这样可以在上传宝塔前验证完整业务流程。只有域名 HTTPS、宝塔反向代理、服务器数据卷和服务器出口 IP 白名单必须部署后再验收。

## 生产配置

复制 `.env.example` 为 `.env`，至少填写：

```dotenv
TOOLKIT_INTHELOOP_PASSWORD=团队管理密码
ITL_SESSION_SECRET=一段足够长的随机字符串
GEEKPARK_LOGIN_NAME=官网账号
GEEKPARK_LOGIN_PASSWORD=官网密码
ITL_AGENT_API_KEY=供其他 Agent 调用的随机密钥
MODELINK_API_KEY=Modelink 提供的 API Key
```

微信公众号 AppID / AppSecret 可以在登录后的公众号 Tab 保存，也可以使用 `.env` 中的 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET`。

直接发布成功后，公开文章链接固定使用 `https://www.geekpark.net/news/{文章ID}`；后台编辑链接仅用于继续修改，不再冒充公开链接。

完整开发交接见 `docs/DEVELOPMENT_GUIDE.md`，部署步骤见 `docs/BAOTA_DEPLOY.md`，Agent 调用见 `docs/AGENT_API.md`。

工作台与独立官网的分仓部署见 `docs/INTHELOOP_DEPLOY.md`。

如果不清楚 API Key 和账号应该填在哪里，直接把 `docs/ENV_SETUP.md` 交给部署人员即可。

## 验证命令

```bash
npm run lint
npm run build
PYTHONPATH=backend python -m pytest -q backend/tests
docker compose config
```
