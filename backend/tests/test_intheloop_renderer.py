from __future__ import annotations

from agents.intheloop.renderer import render_intheloop_html
from agents.intheloop.schema import InTheLoopArticle, InTheLoopBlock


def test_renderer_matches_intheloop_typography_contract() -> None:
    article = InTheLoopArticle(
        title="测试稿",
        author="作者甲",
        editor="编辑乙",
        digest="这是一段 **重要摘要**。",
        header_source="测试来源",
        blocks=[
            InTheLoopBlock(type="paragraph", content="开场正文", source_block_id="p1"),
            InTheLoopBlock(type="heading", content="第一章", source_block_id="h1"),
            InTheLoopBlock(type="paragraph", content="包含 **重点内容** 的正文。", source_block_id="p2"),
            InTheLoopBlock(type="question", content="为什么？", source_block_id="q1"),
            InTheLoopBlock(type="answer", speaker="受访者", content="因为如此。", source_block_id="a1"),
            InTheLoopBlock(type="image", url="https://example.com/image.jpg", source_block_id="i1"),
        ],
    )

    rendered = render_intheloop_html(article)

    assert rendered.index("Why It Matters") < rendered.index("作者｜")
    assert "font-size:16px;line-height:1.75" in rendered
    assert "margin:0 8px 24px;text-align:justify" in rendered
    assert "font-size:18px;line-height:1.45;font-weight:700" in rendered
    assert "width:50px !important" in rendered
    assert "margin-top:24px;margin-bottom:24px" in rendered
    assert "color:#A583FF;font-weight:700" in rendered
    assert "*头图来源：测试来源" in rendered
    assert "本文为 In The Loop 原创文章，转载请联系作者" in rendered
    assert "font-size:14px" in rendered


def test_why_it_matters_starts_without_leading_spacer() -> None:
    rendered = render_intheloop_html(InTheLoopArticle(digest="摘要"))

    article_start = rendered.index("intheloop-article")
    why_start = rendered.index("Why It Matters")
    opening_markup = rendered[article_start:why_start]
    assert "margin:0 8px 24px" in opening_markup
    assert "<br" not in opening_markup
