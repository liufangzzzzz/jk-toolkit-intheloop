"""Conservative, local tag suggestions ordered for editorial review.

Industry, company and person tags come first. Only explicit company/action,
company suffix, named-role and named-product contexts are used. Bylines,
interview speaker labels and arbitrary capitalized words are not entities.
"""
from __future__ import annotations

import re
from bs4 import BeautifulSoup

_INDUSTRIES = [
    ("具身智能", ("具身智能", "embodied ai", "embodied intelligence", "physical ai", "全身智能")),
    ("人形机器人", ("人形机器人", "humanoid")),
    ("自动驾驶", ("自动驾驶", "智驾", "autonomous driving")),
    ("机器人", ("机器人", "robotics")),
    ("芯片", ("芯片", "半导体", "gpu")),
    ("人工智能", ("人工智能", "大模型", "artificial intelligence")),
]
_NAME = r"[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff .&+-]{1,29}?"
_ROLE = r"(?:联合创始人|创始人|CEO)"
_ACTION = r"(?:今日|近日|正式|宣布|全球|首次|重磅|再次|即将|最新|相继|陆续|同步|将|已|了)*\s*(?:发布|推出|完成融资|获得融资|宣布)"
_BAD_COMPANY = re.compile(
    r"(?:唯一|首个|首家|第一|领先|全球|国内|中国|一家|我们|你们|他们|作者|记者|编辑|采访|"
    r"表示|认为|报道|来自|推出|发布|关于|随着|通过|模型|产品|行业|文章|测试|研发|正在|已经|同时|目前|近期|今天|昨天|今年|去年|未来|近日|今日|随后|这|此|该|其|的|了|我)"
)
_GENERIC = {"人工智能", "具身智能", "全身智能", "人形机器人", "机器人", "科技公司", "公司", "团队", "研究团队", "AI", "CEO"}
_COMPANY_SUFFIX = r"(?:科技|智能|机器人|动力|创新|集团|实验室|研究院)"


def suggest_tags(title: str, abstract: str, content_html: str) -> list[str]:
    text = BeautifulSoup(content_html or "", "html.parser").get_text("\n", strip=True)
    # Remove byline rows before entity extraction, including the user's name.
    lines = [line for line in [title, abstract, *text[:10000].splitlines()]
             if not re.match(r"^\s*(?:作者|记者|编辑|文|撰文|采访|校对)\s*[：:丨|/／]", line)]
    source = "\n".join(lines)
    companies: list[str] = []
    people: list[str] = []
    products: list[str] = []

    def add(target: list[str], value: str, limit: int = 2) -> None:
        value = re.sub(r"\s+", " ", value).strip(' ，。；：:、（）()《》“”\"\'')
        if value and value not in target and len(target) < limit:
            target.append(value)

    def company(value: str) -> None:
        value = value.strip()
        if value not in _GENERIC and not _BAD_COMPANY.search(value) and len(value) <= 24:
            add(companies, value)

    # Treat punctuation/metadata as boundaries, never match a suffix in the
    # middle of arbitrary prose (e.g. "唯一一家机器人公司"). Title comes first.
    normalized = re.sub(r"【[^】]*】|\[[^\]]*\]", "\n", source)
    boundary = r"(?:^|[\n。！？；，：:])\s*"
    for pattern in [
        boundary + rf"({_NAME})\s*(?:的)?{_ROLE}",
        boundary + rf"({_NAME})\s*{_ACTION}",
    ]:
        for match in re.finditer(pattern, normalized):
            company(match.group(1))

    # Company-like names in the headline or abstract are useful even when the
    # sentence does not use a release verb. Keep this constrained to common
    # organization suffixes to avoid turning arbitrary prose into tags.
    headline = "\n".join([title, abstract])
    for match in re.finditer(rf"(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{{2,12}}{_COMPANY_SUFFIX})(?![\u4e00-\u9fff])", headline):
        company(match.group(1))

    # Founder names require a company context, rather than just "张三：" or a byline.
    person = r"([\u4e00-\u9fff]{2,4}?|[A-Z][a-z]+(?: [A-Z][a-z]+){1,2})"
    person_end = r"(?=表示|认为|说|谈|接受|出席|发布|介绍|指出|[\s，。；：:（(]|$)"
    for name in companies:
        prefix = re.escape(name) + rf"\s*(?:的)?{_ROLE}(?:\s*(?:兼|暨|、|&|及)\s*(?:CEO|首席执行官))?\s*[：:]?\s*"
        for match in re.finditer(prefix + person + person_end, source):
            value = match.group(1)
            if value not in {"表示", "认为", "我们", "唯一"}:
                add(people, value)

    # A role is strong enough evidence for a person tag even when the company
    # name was written elsewhere in the article.
    for match in re.finditer(_ROLE + r"(?:\s*(?:兼|暨|、|&|及)\s*(?:CEO|首席执行官))?\s*[：:]?\s*" + person + person_end, source):
        value = match.group(1)
        if value not in {"表示", "认为", "我们", "唯一"}:
            add(people, value)
    for match in re.finditer(person + r"\s*[，,]\s*[^\n。！？]{0,30}?" + _ROLE, source):
        add(people, match.group(1))

    # Only named model/product contexts, not every English term in an article.
    latin_product = r"([A-Za-z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*(?: [A-Z0-9][A-Za-z0-9.-]*){0,2})"
    for match in re.finditer(r"(?:模型|产品|平台|机器人|芯片|系统)\s*[：:「“\"]?\s*" + latin_product, source):
        value = match.group(1).strip()
        if value not in _GENERIC and not re.search(r"^(?:AI|CEO|GPU|Physical AI)$", value):
            add(products, value)
    for match in re.finditer(r"(?:发布|推出|开源)[^\n。！？]{0,25}?[「“]([^」”\n]{2,20})[」”]", source):
        value = match.group(1)
        if not re.search(r"唯一|首次|领先|我们|的", value):
            add(products, value)

    haystack = source.lower()
    industries = [label for label, words in _INDUSTRIES if any(word in haystack for word in words)]
    # Keep the most specific industry match. The ordered taxonomy places broad
    # fallbacks such as “机器人” and “人工智能” after specific sectors.
    industry = industries[0] if industries else None
    # Stable review order keeps the named entities together: companies,
    # people and industry all precede products or broad editorial topics.
    return list(dict.fromkeys([*companies, *people, *([industry] if industry else []), *products]))[:7]
