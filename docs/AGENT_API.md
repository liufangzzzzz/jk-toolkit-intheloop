# 官网同步 Agent API

接口前缀：`/api/v1/agent/website`

每次请求必须带：

```http
X-Agent-Key: <ITL_AGENT_API_KEY>
```

`idempotency_key` 必须由调用方生成并在重试时保持不变。相同键不会重复创建或发布文章。

## 导入微信文章

```bash
curl -X POST 'https://toolkit-intheloop.geekpark.net/api/v1/agent/website/import-url' \
  -H 'Content-Type: application/json' \
  -H 'X-Agent-Key: YOUR_AGENT_KEY' \
  -d '{
    "source_url": "https://mp.weixin.qq.com/s/ARTICLE",
    "mode": "draft",
    "column_id": null,
    "tags": ["具身智能"],
    "idempotency_key": "source-system:article-123:v1"
  }'
```

`mode` 为 `draft` 时保存官网草稿，为 `publish` 时直接发布。

## 导入 Word

```bash
curl -X POST 'https://toolkit-intheloop.geekpark.net/api/v1/agent/website/import-file' \
  -H 'X-Agent-Key: YOUR_AGENT_KEY' \
  -F 'file=@article.docx' \
  -F 'mode=draft' \
  -F 'column_id=' \
  -F 'tags=具身智能,机器人' \
  -F 'idempotency_key=source-system:document-456:v1'
```

支持 `.docx` 和 `.doc`，单个文件最大 30MB。

## 查询任务

导入接口返回结果中的 `id` 是任务 ID：

```bash
curl 'https://toolkit-intheloop.geekpark.net/api/v1/agent/website/jobs/JOB_ID' \
  -H 'X-Agent-Key: YOUR_AGENT_KEY'
```

任务状态为 `processing`、`completed` 或 `failed`。同步调用通常会直接返回最终状态，但查询接口可用于调用方保存记录和重试核对。

