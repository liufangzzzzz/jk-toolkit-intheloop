from __future__ import annotations

import asyncio
import io
import sqlite3
import zipfile

import httpx
from fastapi.testclient import TestClient

from app import database as database_module
from app.main import app
from app.modules.website_ingest import parser
from app.modules.website_ingest import publisher
from app.modules.website_ingest.models import WebsiteImportArticle


def _minimal_docx() -> bytes:
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        "word/_rels/document.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""",
        "word/styles.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
</w:styles>""",
        "word/document.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>机器人进入工厂</w:t></w:r></w:p>
    <w:p><w:r><w:t>这是一篇具身智能测试文章。</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>""",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def test_word_parser_extracts_title_summary_and_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path / "assets"))

    article = parser.parse_word_file(_minimal_docx(), "测试稿.docx")

    assert article.title == "机器人进入工厂"
    assert "具身智能测试文章" in article.abstract
    assert "具身智能" in article.tags
    assert article.source_type == "docx"
    assert "<h1" not in article.content_html


def test_wechat_parser_localizes_images_and_removes_unsafe_markup(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path / "assets"))
    page = """
    <html><head>
      <meta name="description" content="文章摘要">
      <meta property="og:image" content="https://mmbiz.qpic.cn/cover.jpg">
    </head><body>
      <h1 id="activity-name">微信机器人文章</h1>
      <section id="js_content">
        <p>具身智能正文</p>
        <img data-src="https://mmbiz.qpic.cn/body.jpg" alt="正文图">
        <iframe src="https://v.qq.com/video"></iframe><script>alert(1)</script>
      </section>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mp.weixin.qq.com":
            return httpx.Response(200, text=page, request=request)
        return httpx.Response(200, content=b"jpeg-bytes", headers={"content-type": "image/jpeg"}, request=request)

    real_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(parser.httpx, "AsyncClient", mock_client)
    article = asyncio.run(parser.parse_wechat_url("https://mp.weixin.qq.com/s/test"))

    assert article.title == "微信机器人文章"
    assert "ingest-asset://" in article.content_html
    assert "<script" not in article.content_html
    assert "<iframe" not in article.content_html
    assert article.cover_asset.startswith("ingest-asset://")
    assert any("1 个视频模块" in warning for warning in article.warnings)


def test_database_migrates_existing_publish_records(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE publish_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destination TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                external_id TEXT NOT NULL DEFAULT '',
                external_url TEXT NOT NULL DEFAULT '',
                admin_url TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    monkeypatch.setenv("ITL_DATABASE_PATH", str(path))
    database_module._INITIALIZED_PATHS.discard(str(path.resolve()))

    database_module.initialize_database()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(publish_records)")}
    assert "request_id" in columns


def test_agent_api_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("ITL_AGENT_API_KEY", "correct-agent-key")
    response = TestClient(app).post(
        "/api/v1/agent/website/import-url",
        headers={"X-Agent-Key": "wrong-agent-key"},
        json={
            "source_url": "https://mp.weixin.qq.com/s/test",
            "mode": "draft",
            "idempotency_key": "test-job-1",
        },
    )
    assert response.status_code == 401


def test_website_publish_contract_supports_direct_publish(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_DATABASE_PATH", str(tmp_path / "publish.db"))
    database_module._INITIALIZED_PATHS.discard(str((tmp_path / "publish.db").resolve()))
    captured = {}

    async def fake_connect(*, force=False):
        return {"connected": True, "fixed_credentials": True}

    async def fake_prepare(article, access_key):
        assert access_key == "test-access-key"
        return "<p>官网正文</p>", {"url": "https://img.example/cover.jpg", "id": "cover-1"}, []

    class FakeResponse:
        status_code = 201
        text = ""

        @staticmethod
        def json():
            return {"id": 789, "url": "https://www.geekpark.net/news/789"}

    async def fake_post(payload, access_key):
        captured.update(payload)
        assert access_key == "test-access-key"
        return FakeResponse()

    monkeypatch.setattr(publisher, "connect_fixed_account", fake_connect)
    monkeypatch.setattr(
        publisher,
        "load_settings",
        lambda: {"website": {"access_key": "test-access-key", "author_id": "author-uuid", "column_id": 456}},
    )
    monkeypatch.setattr(publisher, "_prepare_images", fake_prepare)
    monkeypatch.setattr(publisher, "_post_article", fake_post)

    result = asyncio.run(
        publisher.publish_article(
            WebsiteImportArticle(
                title="测试稿",
                abstract="摘要",
                content_html="<p>正文</p>",
                tags=["机器人", "机器人", "具身智能"],
                source_type="docx",
                source_ref="test.docx",
            ),
            mode="publish",
            column_id=None,
            request_id="website-contract-1",
        )
    )

    assert result["article_id"] == 789
    assert captured["state"] == "published"
    assert captured["authors"] == ["author-uuid"]
    assert captured["column_id"] == 456
    assert captured["cover_id"] == "cover-1"
    assert captured["cover_url"] == "https://img.example/cover.jpg"
    assert captured["tags"] == ["机器人", "具身智能"]
