from __future__ import annotations

import asyncio
import io
import sqlite3
import zipfile

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app import database as database_module
from app.main import app
from app.modules.website_ingest import parser
from app.modules.website_ingest import publisher
from app.modules.website_ingest.assets import save_asset
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


def test_short_abstract_uses_complete_opening_sentences():
    source = "第一句话说明文章的核心背景。第二句话补充必要事实。" + "很长的后续内容，" * 30
    assert parser._short_abstract(source) == "第一句话说明文章的核心背景。第二句话补充必要事实。"
    assert len(parser._short_abstract("没有句号的很长内容，" * 30)) <= 151


def test_website_status_exposes_two_separate_env_accounts(monkeypatch):
    monkeypatch.setenv("GEEKPARK_LOGIN_NAME", "first@example.com")
    monkeypatch.setenv("GEEKPARK_LOGIN_PASSWORD", "first-secret")
    monkeypatch.setenv("GEEKPARK_ACCOUNT_NAME", "主账号")
    monkeypatch.setenv("GEEKPARK_LOGIN_NAME_2", "second@example.com")
    monkeypatch.setenv("GEEKPARK_LOGIN_PASSWORD_2", "second-secret")
    monkeypatch.setenv("GEEKPARK_ACCOUNT_NAME_2", "第二账号")
    monkeypatch.setattr(publisher, "load_settings", lambda: {
        "website": {"access_key": "key-1", "nickname": "作者一"},
        "website_2": {"access_key": "key-2", "nickname": "作者二"},
    })

    status = publisher.connection_status("2")

    assert status["account_id"] == "2"
    assert status["nickname"] == "作者二"
    assert status["connected"] is True
    assert status["accounts"] == [
        {"id": "default", "label": "主账号"},
        {"id": "2", "label": "第二账号"},
    ]


def test_default_account_label_uses_connected_author_name(monkeypatch):
    monkeypatch.setenv("GEEKPARK_LOGIN_NAME", "li@example.com")
    monkeypatch.setenv("GEEKPARK_LOGIN_PASSWORD", "secret")
    monkeypatch.setenv("GEEKPARK_ACCOUNT_NAME", "默认官网账号")
    monkeypatch.delenv("GEEKPARK_LOGIN_NAME_2", raising=False)
    monkeypatch.delenv("GEEKPARK_LOGIN_PASSWORD_2", raising=False)
    monkeypatch.setattr(publisher, "load_settings", lambda: {
        "website": {"access_key": "key", "nickname": "Li Yuan"},
    })

    status = publisher.connection_status()

    assert status["account_label"] == "Li Yuan"
    assert status["accounts"] == [{"id": "default", "label": "Li Yuan"}]


def test_preview_streams_assets_instead_of_embedding_base64(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path))
    reference = save_asset(b"jpeg-bytes", "image/jpeg")
    article = WebsiteImportArticle(
        title="测试",
        abstract="摘要",
        content_html=f'<p>正文</p><img src="{reference}">',
        source_type="docx",
        source_ref="test.docx",
    )

    preview = parser.render_preview(article)

    assert "data:image" not in preview
    assert reference in preview
    assert f'/api/v1/website-import/assets/{reference.removeprefix("ingest-asset://")}' in preview


def test_image_upload_accepts_nested_success_response(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path))
    reference = save_asset(b"jpeg-bytes", "image/jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            json={"data": {"image": {"image_url": "http://cdn.geekpark.net/image.jpg", "image_id": 42}}},
            request=request,
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        publisher.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )

    image = asyncio.run(publisher._upload_image(reference, "access-key"))

    assert image == {"url": "https://cdn.geekpark.net/image.jpg", "id": 42}


def test_image_upload_uses_location_header_when_body_has_no_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path))
    reference = save_asset(b"jpeg-bytes", "image/jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            headers={"location": "http://cdn.geekpark.net/from-location.jpg"},
            request=request,
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        publisher.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )

    image = asyncio.run(publisher._upload_image(reference, "access-key"))

    assert image["url"] == "https://cdn.geekpark.net/from-location.jpg"


def test_image_upload_compresses_and_retries_after_413(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path))
    source = io.BytesIO()
    Image.new("RGB", (80, 80), "purple").save(source, format="PNG")
    reference = save_asset(source.getvalue(), "image/png")
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.content)
        if len(attempts) == 1:
            return httpx.Response(413, text="too large", request=request)
        return httpx.Response(201, json={"image": {"url": "https://cdn.geekpark.net/retried.jpg"}}, request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        publisher.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)),
    )

    image = asyncio.run(publisher._upload_image(reference, "access-key"))

    assert len(attempts) == 2
    assert b"image/jpeg" in attempts[1]
    assert image["url"] == "https://cdn.geekpark.net/retried.jpg"


def test_sanitizer_preserves_safe_colors_and_normalizes_heading_size():
    cleaned = parser.sanitize_fragment(
        '<h2 style="font-size:88px;color:#A583FF;background-color:rgb(250, 240, 255);position:fixed">标题</h2>'
        '<p style="color:#c21;background-image:url(javascript:alert(1))">正文</p>'
    )

    assert "color:#A583FF" in cleaned
    assert "background-color:rgb(250, 240, 255)" in cleaned
    assert "font-size:18px" in cleaned
    assert "88px" not in cleaned
    assert "position" not in cleaned
    assert "javascript" not in cleaned


def test_preview_streams_local_images(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path / "assets"))
    reference = save_asset(b"png-content", "image/png")
    article = WebsiteImportArticle(
        title="预览图片",
        content_html=f'<p><img src="{reference}" alt="示例"></p>',
        source_type="docx",
    )

    preview = parser.render_preview(article)

    assert 'src="/api/v1/website-import/assets/' in preview
    assert f'data-asset-ref="{reference}"' in preview
    assert 'id="website-content"' in preview


def test_tag_suggestions_prioritize_company_and_person_names():
    tags = parser.suggest_tags(
        "Figure AI CEO 王强谈人形机器人",
        "星河智能创始人李雷接受采访",
        "<p>具身智能行业进入新阶段。</p>",
    )

    assert tags.index("Figure AI") < tags.index("具身智能")
    assert "星河智能" in tags
    assert "王强" in tags
    assert "李雷" in tags


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


def test_wechat_parser_recognizes_image_bytes_with_generic_content_type(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path / "assets"))
    page = '<h1 id="activity-name">图片测试</h1><section id="js_content"><img data-src="https://mmbiz.qpic.cn/body.jpg"></section>'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mp.weixin.qq.com":
            return httpx.Response(200, text=page, request=request)
        return httpx.Response(
            200,
            content=b"\xff\xd8\xff" + b"jpeg-content",
            headers={"content-type": "application/octet-stream"},
            request=request,
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        parser.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )

    article = asyncio.run(parser.parse_wechat_url("https://mp.weixin.qq.com/s/test"))

    assert "ingest-asset://" in article.content_html
    assert not article.image_issues


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

    async def fake_connect(account_id="default", *, force=False):
        return {"connected": True, "fixed_credentials": True, "account_id": account_id}

    async def fake_prepare(article, access_key):
        assert access_key == "test-access-key"
        return "<p>官网正文</p>", {"url": "https://img.example/cover.jpg", "id": "cover-1"}, [], []

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
    assert "auto_publish_at" not in captured
    assert "roles" not in captured
    assert "column" not in captured
    assert result["public_url"] == "https://www.geekpark.net/news/789"


def test_post_article_sends_auth_in_query_not_json(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = dict(request.url.params)
        captured["json"] = request.content.decode("utf-8")
        return httpx.Response(201, json={"id": 1}, request=request)

    real_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(publisher.httpx, "AsyncClient", mock_client)
    response = asyncio.run(publisher._post_article({"title": "测试"}, "access-key"))

    assert response.status_code == 201
    assert captured["query"] == {"roles": "dev", "access_key": "access-key"}
    assert '"access_key"' not in captured["json"]


def test_word_publish_prefers_industry_news_column(tmp_path, monkeypatch):
    monkeypatch.setenv("ITL_DATABASE_PATH", str(tmp_path / "industry.db"))
    database_module._INITIALIZED_PATHS.discard(str((tmp_path / "industry.db").resolve()))
    captured = {}

    async def fake_connect(account_id="default", *, force=False):
        return {"connected": True, "fixed_credentials": True, "account_id": account_id}

    async def fake_prepare(article, access_key):
        return "<p>正文</p>", {"url": "", "id": ""}, [], []

    class FakeResponse:
        status_code = 201
        text = ""

        @staticmethod
        def json():
            return {"id": 1001}

    async def fake_post(payload, access_key):
        captured.update(payload)
        return FakeResponse()

    monkeypatch.setattr(publisher, "connect_fixed_account", fake_connect)
    monkeypatch.setattr(
        publisher,
        "load_settings",
        lambda: {"website": {
            "access_key": "key",
            "author_id": "author",
            "column_id": 99,
            "columns": [{"id": 99, "title": "其他"}, {"id": 2, "title": "行业资讯"}],
        }},
    )
    monkeypatch.setattr(publisher, "_prepare_images", fake_prepare)
    monkeypatch.setattr(publisher, "_post_article", fake_post)

    asyncio.run(publisher.publish_article(
        WebsiteImportArticle(title="Word 稿", content_html="<p>正文</p>", source_type="docx"),
        mode="draft",
        column_id=None,
        request_id="industry-column-1",
    ))

    assert captured["column_id"] == 2


def test_word_size_boundary_accepts_limit_and_rejects_larger(tmp_path, monkeypatch):
    import pytest
    raw = _minimal_docx()
    assert parser._MAX_DOCUMENT_BYTES == 60 * 1024 * 1024
    monkeypatch.setenv("ITL_IMPORT_ASSET_PATH", str(tmp_path / "assets"))
    # Exercise the same inclusive boundary with a small valid document.
    monkeypatch.setattr(parser, "_MAX_DOCUMENT_BYTES", len(raw))
    assert parser.parse_word_file(raw, "稿件.docx").title
    with pytest.raises(ValueError, match="超过 60MB"):
        parser.parse_word_file(raw + b"x", "稿件.docx")
