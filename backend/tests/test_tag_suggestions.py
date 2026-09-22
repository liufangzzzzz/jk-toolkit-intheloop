from app.modules.website_ingest.tags import suggest_tags


def test_company_without_generic_suffix_and_named_model():
    tags = suggest_tags('【新闻稿】亮源新创发布全身智能基础模型Light-O1', '', '<p>亮源新创已相继推出技术成果。</p><p>此次发布的Light-O1确立了技术路径。</p>')
    assert tags == ['亮源新创', '具身智能', 'Light-O1']


def test_only_explicit_founders_not_authors_or_speaker_labels():
    tags = suggest_tags('星河智能推出机器人', '', '<p>作者：Yuan</p><p>编辑：李明</p><p>我：这是唯一一家领先公司。</p><p>王强：我们很高兴。</p><p>星河智能创始人李雷表示，公司正在研发机器人。</p>')
    assert tags == ['星河智能', '李雷', '机器人']


def test_does_not_convert_promotional_phrases_to_company_names():
    tags = suggest_tags('唯一一家机器人公司发布新产品', '', '<p>全球领先的科技公司推出新模型。</p>')
    assert tags == ['机器人']


def test_no_generic_fallback_or_arbitrary_english_terms():
    assert suggest_tags('观点', '', '<p>作者：Yuan</p><p>Scalable Alignment 是一种方法。</p>') == []


def test_named_chinese_product_and_founder():
    tags = suggest_tags('星河智能推出“星舟”机器人', '', '<p>星河智能联合创始人兼CEO张三表示，我们正在测试。</p>')
    assert tags == ['星河智能', '张三', '机器人', '星舟']
