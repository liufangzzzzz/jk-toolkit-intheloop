import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.modules.atlas import store

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('ITL_DATABASE_PATH',str(tmp_path/'test.db'))
    monkeypatch.setenv('ITL_SETTINGS_PATH',str(tmp_path/'settings.json'))
    monkeypatch.setenv('ITL_ACCESS_PASSWORD','test-password')
    monkeypatch.setenv('ITL_COOKIE_SECURE','false')
    c=TestClient(app)
    c.post('/api/v1/auth/login',json={'password':'test-password'})
    return c

def create(client,kind,body):
    response=client.post('/api/v1/atlas/'+kind,json=body)
    assert response.status_code==200,response.text
    return response.json()['id']

def article(**kw):
    return {'kind':'article','date':'2026-09-21','versions':{'zh':{'title':'中文原稿','body':'计划量产'},'en':{'title':'English draft','body':'Plans to start production'}},**kw}

def test_private_routes_require_login(client):
    anonymous=TestClient(app)
    assert anonymous.get('/api/v1/atlas').status_code==401
    assert anonymous.post('/api/v1/atlas/companies',json={}).status_code==401
    assert anonymous.get('/api/v1/public/atlas/zh').status_code==200

def test_company_overlap_and_evidence_private(client):
    a=create(client,'tags',{'slug':'vla','name_zh':'VLA','dimension':'technology'})
    b=create(client,'tags',{'slug':'world-model','name_zh':'世界模型','dimension':'technology'})
    c=create(client,'tags',{'slug':'wheeled','name_zh':'轮式双臂','dimension':'form'})
    company=create(client,'companies',{'slug':'test-company','name_zh':'测试公司','visible_locales':['zh'],'tag_links':[{'tag_id':x,'note':'内部证据','evidence_url':'https://example.com'} for x in [a,b,c]]})
    public=client.get('/api/v1/public/atlas/zh').json()
    assert public['companies'][0]['tag_ids']==[a,b,c] or set(public['companies'][0]['tag_ids'])=={a,b,c}
    assert '内部证据' not in str(public)
    assert client.get('/api/v1/public/atlas/en').json()['companies']==[]
    data=client.get('/api/v1/atlas').json()
    record=data['companies'][0]
    record['summary_zh']='new'
    assert client.put('/api/v1/atlas/companies/'+company,json=record).status_code==200
    assert client.put('/api/v1/atlas/companies/'+company,json=record).status_code==409

def test_language_publish_snapshot_and_withdrawal(client):
    identifier=create(client,'contents',article())
    assert client.get('/api/v1/public/atlas/zh').json()['contents']==[]
    assert client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'zh','revision':1}).status_code==200
    assert client.get('/api/v1/public/atlas/en').json()['contents']==[]
    old=client.get('/api/v1/public/atlas/zh').json()['contents'][0]
    assert set(old['versions'])=={'zh'}
    updated=article(revision=1)
    updated['versions']['zh']['title']='尚未发布的修改'
    assert client.put('/api/v1/atlas/contents/'+identifier,json=updated).status_code==200
    assert client.get('/api/v1/public/atlas/zh').json()['contents'][0]['versions']['zh']['title']=='中文原稿'
    assert client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'zh','revision':1}).status_code==409
    assert client.delete(f'/api/v1/atlas/contents/{identifier}/publish/zh').status_code==200
    assert client.get('/api/v1/public/atlas/zh').json()['contents']==[]

def test_bad_relation_rollback(client):
    response=client.post('/api/v1/atlas/contents',json=article(company_ids=['missing']))
    assert response.status_code==409
    assert client.get('/api/v1/atlas').json()['contents']==[]

def test_unsafe_link_and_slug(client):
    assert client.post('/api/v1/atlas/companies',json={'slug':'../../oops','name_zh':'测试'}).status_code==422
    assert client.post('/api/v1/atlas/contents',json=article(source_url='javascript:alert(1)')).status_code==422

def test_models_explicit_and_no_key_exposure(client,monkeypatch):
    monkeypatch.setenv('MODELINK_API_KEY','secret-never-show')
    monkeypatch.setenv('MODELINK_BASE_URL','https://example.com/v1')
    r=client.get('/api/v1/atlas/models')
    assert r.json()['configured']
    assert 'secret-never-show' not in r.text
    assert [item['id'] for item in r.json()['models']] == [
        'deepseek/deepseek-v4-flash-vision-exp',
        'anthropic/claude-4.8-opus',
        'anthropic/claude-opus-5',
        'openai/gpt-5.6-terra',
    ]
    assert client.post('/api/v1/atlas/generate',json={'model':'unknown','task':'english','text':'原文'}).status_code==422
    assert client.post('/api/v1/atlas/generate',json={'model':'','task':'english','text':'原文'}).status_code==422

def test_podcast_english_requires_summary(client):
    record=article(kind='podcast',source_url='https://www.xiaoyuzhoufm.com/episode/example')
    record['versions']['en']['summary']='English summary that would otherwise be publishable.'
    identifier=create(client,'contents',record)
    saved=next(c for c in client.get('/api/v1/atlas').json()['contents'] if c['id']==identifier)
    assert saved['chinese_only'] is True
    assert 'editorial:podcast' in saved['tag_ids']
    response=client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'en','revision':1})
    assert response.status_code==409
    assert '仅发布到中文官网' in response.text
    assert client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'zh','revision':1}).status_code==200

def test_editorial_filters_are_hidden_primary_tags(client):
    tags={tag['id']:tag for tag in client.get('/api/v1/atlas').json()['tags']}
    for identifier in ('editorial:article','editorial:podcast','editorial:worldview','editorial:thinking','editorial:overseas'):
        assert tags[identifier]['map_level']=='primary'
        assert tags[identifier]['map_visible'] is False
        assert tags[identifier]['visible_locales']==['zh']

def test_publication_relationship_is_snapshot(client):
    cid=create(client,'companies',{'slug':'company','name_zh':'公司','visible_locales':['zh']})
    identifier=create(client,'contents',article(company_ids=[cid]))
    client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'zh','revision':1})
    client.put('/api/v1/atlas/contents/'+identifier,json=article(revision=1,company_ids=[]))
    assert client.get('/api/v1/public/atlas/zh').json()['contents'][0]['company_ids']==[cid]

def test_external_chinese_and_hosted_english(client):
    record = article(source_url='https://mp.weixin.qq.com/s/example')
    record['versions']['zh'].update(destination='external', body='')
    record['versions']['en'].update(destination='hosted')
    identifier = create(client, 'contents', record)
    for locale in ('zh', 'en'):
        assert client.post(f'/api/v1/atlas/contents/{identifier}/publish', json={'locale':locale,'revision':1}).status_code == 200
        version = client.get('/api/v1/public/atlas/'+locale).json()['contents'][0]['versions']
        assert set(version) == {locale}
        assert version[locale]['destination'] == ('external' if locale == 'zh' else 'hosted')
    bad = article()
    bad['versions']['zh']['external_url'] = 'javascript:alert(1)'
    assert client.post('/api/v1/atlas/contents', json=bad).status_code == 422

def test_text_file_import_and_external_missing_link(client):
    r = client.post('/api/v1/atlas/import', files={'file':('notes.md', '# 内容沉淀\n\n记录正文。'.encode(), 'text/markdown')})
    assert r.status_code == 200
    assert r.json()['title'] == '内容沉淀'
    assert '记录正文' in r.json()['body']
    record = article(kind='link')
    record['versions']['zh']['destination'] = 'external'
    identifier = create(client, 'contents', record)
    assert client.post(f'/api/v1/atlas/contents/{identifier}/publish', json={'locale':'zh','revision':1}).status_code == 409

def test_import_url_text_only_and_redirect_boundary(client, monkeypatch):
    import httpx
    from app.modules.atlas import extract
    original = httpx.AsyncClient
    monkeypatch.setattr(extract.socket, 'getaddrinfo', lambda host, port, *a, **kw: [(extract.socket.AF_INET,extract.socket.SOCK_STREAM,6,'',('127.0.0.1' if host in ('localhost','127.0.0.1') else '93.184.216.34',port))])
    seen = []
    def handler(request):
        seen.append(str(request.url))
        assert request.headers['host'] in ('mp.weixin.qq.com','geekpark.net','figure.ai')
        assert request.extensions['sni_hostname'] == request.headers['host']
        if request.url.path == '/redirect': return httpx.Response(302, headers={'location':'http://127.0.0.1/private'})
        return httpx.Response(200, headers={'content-type':'text/html'}, text='<h1>文章标题</h1><div id="js_content"><p>'+('可以翻译的文字。'*15)+'</p><img src="https://private/image"><script>bad()</script></div>')
    monkeypatch.setattr(extract.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    r = client.post('/api/v1/atlas/import-url', json={'url':'https://mp.weixin.qq.com/s/abc'})
    assert r.status_code == 200
    assert r.json()['title'] == '文章标题'
    assert 'bad()' not in r.json()['body']
    assert len(seen) == 1
    assert client.post('/api/v1/atlas/import-url',json={'url':'https://geekpark.net/redirect'}).status_code == 422
    assert len(seen) == 2
    assert client.post('/api/v1/atlas/import-url',json={'url':'http://localhost/private'}).status_code == 422
    assert len(seen) == 2
    assert client.post('/api/v1/atlas/import-url',json={'url':'https://figure.ai/news/example'}).status_code == 200

def test_tag_graph_visibility_and_cycle_validation(client):
    root = create(client,'tags',{'slug':'body','name_zh':'机器人本体','dimension':'form','map_visible':True})
    child = create(client,'tags',{'slug':'humanoid','name_zh':'人形机器人','dimension':'form','parent_ids':[root],'map_visible':False})
    brain = create(client,'tags',{'slug':'brain','name_zh':'机器人大脑','dimension':'technology','related_tag_ids':[child]})
    company = create(client,'companies',{'slug':'test','name_zh':'示例公司','map_visible':False,'visible_locales':['zh'],'tag_links':[{'tag_id':child},{'tag_id':brain}]})
    records=client.get('/api/v1/atlas').json()
    c=next(t for t in records['tags'] if t['id']==child)
    assert c['related_tag_ids']==[brain]
    assert c['parent_ids']==[root]
    r=next(t for t in records['tags'] if t['id']==root)
    assert client.put('/api/v1/atlas/tags/'+root,json={**r,'parent_ids':[child]}).status_code==409
    public=client.get('/api/v1/public/atlas/zh').json()
    assert next(c for c in public['companies'] if c['id']==company)['map_visible'] is False
    assert next(t for t in public['tags'] if t['id']==child)['map_visible'] is False
    assert child in next(c for c in public['companies'] if c['id']==company)['tag_ids']
    hidden=create(client,'tags',{'slug':'internal','name_zh':'内部选题','dimension':'technology','visible_locales':[],'related_tag_ids':[brain]})
    public=client.get('/api/v1/public/atlas/zh').json()
    assert hidden not in str(public)

def test_related_tag_changes_update_peer_revision(client):
    a=create(client,'tags',{'slug':'a','name_zh':'A','dimension':'form'})
    stale=client.get('/api/v1/atlas').json()['tags'][0]
    b=create(client,'tags',{'slug':'b','name_zh':'B','dimension':'form','related_tag_ids':[a]})
    assert client.put('/api/v1/atlas/tags/'+a,json=stale).status_code==409
    current=next(t for t in client.get('/api/v1/atlas').json()['tags'] if t['id']==a)
    assert current['related_tag_ids']==[b]
    assert client.put('/api/v1/atlas/tags/'+a,json={**current,'related_tag_ids':[]}).status_code==200
    peer=next(t for t in client.get('/api/v1/atlas').json()['tags'] if t['id']==b)
    assert peer['related_tag_ids']==[]


def test_overseas_is_chinese_only_and_removes_previous_english(client):
    record=article()
    identifier=create(client,'contents',record)
    assert client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'en','revision':1}).status_code==200
    record.update(section='overseas',revision=1)
    assert client.put('/api/v1/atlas/contents/'+identifier,json=record).status_code==200
    assert client.get('/api/v1/public/atlas/en').json()['contents']==[]
    assert client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'en','revision':2}).status_code==409
    assert client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'zh','revision':2}).status_code==200


def test_legacy_entities_migrate_to_tags_once(client):
    from app.database import database
    topic=create(client,'tags',{'slug':'humanoid','name_zh':'人形机器人','dimension':'form'})
    company=create(client,'companies',{'slug':'example','name_zh':'示例公司','visible_locales':['zh'],'tag_links':[{'tag_id':topic}]})
    cid=create(client,'contents',article(company_ids=[company],tag_ids=[topic]))
    client.post(f'/api/v1/atlas/contents/{cid}/publish',json={'locale':'zh','revision':1})
    with database() as db: db.execute("DELETE FROM atlas_migrations WHERE name='unified-tags-v1'")
    data=store.catalogue()
    migrated=next(t for t in data['tags'] if t['id']=='company:'+company)
    assert migrated['map_visible'] is False
    assert migrated['related_tag_ids']==[topic]
    assert next(t for t in data['tags'] if t['id']==topic)['parent_ids']==['category:form']
    public=store.public_catalogue('zh')
    assert migrated['id'] in public['contents'][0]['tag_ids']
    assert len(store.catalogue()['tags'])==len(data['tags'])


def test_companion_resources_and_display_levels(client):
    create(client,'tags',{'slug':'figure','name_zh':'Figure','dimension':'form','map_level':'primary','map_visible':True})
    identifier=create(client,'contents',article(resources=[{'label':'Figure 官网','label_en':'Figure website','url':'https://figure.ai','kind':'website'}]))
    client.post(f'/api/v1/atlas/contents/{identifier}/publish',json={'locale':'en','revision':1})
    public=client.get('/api/v1/public/atlas/en').json()
    assert public['tags'][0]['map_level']=='primary'
    assert public['contents'][0]['resources'][0]['label_en']=='Figure website'
    assert client.post('/api/v1/atlas/contents',json=article(resources=[{'label':'bad','url':'javascript:bad()'}])).status_code==422

def test_english_generation_returns_editable_fields_with_unified_glossary(client,monkeypatch):
    import httpx,json
    from app.modules.atlas import routes
    monkeypatch.setenv('MODELINK_API_KEY','test-key')
    monkeypatch.setenv('MODELINK_BASE_URL','https://models.example/v1')
    chosen_model='openai/gpt-5.6-terra'
    create(client,'tags',{'slug':'figure','name_zh':'Figure','name_en':'Figure AI','aliases':['Figure Robotics'],'dimension':'form'})
    original=httpx.AsyncClient
    def handler(request):
        body=json.loads(request.content)
        assert body['model']==chosen_model
        assert 'Figure AI' in body['messages'][0]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'title':'A report','summary':'A short summary.','body':'English text.'})}}]})
    monkeypatch.setattr(routes.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    response=client.post('/api/v1/atlas/generate',json={'model':chosen_model,'task':'english','text':'这是一篇文字稿。'})
    assert response.status_code==200,response.text
    assert response.json()['version']['title']=='A report'
    assert client.get('/api/v1/public/atlas/en').json()['contents']==[]

def test_modelink_uses_fixed_allowlist_without_remote_discovery(client,monkeypatch):
    import httpx,json
    from app.modules.atlas import routes
    monkeypatch.setenv('MODELINK_API_KEY','modelink-private-test-key')
    monkeypatch.setenv('MODELINK_BASE_URL','https://api.qnaigc.com/v1')
    original=httpx.AsyncClient
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        assert request.headers['authorization']=='Bearer modelink-private-test-key'
        body=json.loads(request.content)
        assert body['model']=='anthropic/claude-opus-5'
        return httpx.Response(200,json={'choices':[{'message':{'content':'A concise summary.'}}]})
    monkeypatch.setattr(routes.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    r=client.get('/api/v1/atlas/models')
    assert r.json()['configured'] and r.json()['provider']=='Modelink'
    assert 'modelink-private-test-key' not in r.text
    assert [x['id'] for x in r.json()['models']]==[
        'deepseek/deepseek-v4-flash-vision-exp',
        'anthropic/claude-4.8-opus',
        'anthropic/claude-opus-5',
        'openai/gpt-5.6-terra',
    ]
    assert client.post('/api/v1/atlas/generate',json={'model':'missing','task':'summary','text':'原稿'}).status_code==422
    assert client.post('/api/v1/atlas/generate',json={'model':'anthropic/claude-opus-5','task':'summary','text':'原稿'}).status_code==200
    assert calls.count('/v1/models')==0
    assert calls.count('/v1/chat/completions')==1


def test_model_list_is_empty_until_server_key_is_configured(client,monkeypatch):
    monkeypatch.delenv('MODELINK_API_KEY',raising=False)
    result=client.get('/api/v1/atlas/models')
    assert result.json()['models']==[]
    assert result.json()['configured'] is False


def test_audio_studio_imports_text_without_ai_and_prompts_before_audio(client, monkeypatch):
    from app.modules.atlas import audio_studio
    async def fail_if_called():
        raise AssertionError('model discovery must not run before explicit audio consent')
    monkeypatch.setattr(audio_studio, 'model_options', fail_if_called)
    text_file = client.post(
        '/api/v1/audio-studio/import-file',
        files={'file': ('episode.txt', '主持人：欢迎来到节目。\n嘉宾：今天谈机器人。'.encode(), 'text/plain')},
    )
    assert text_file.status_code == 200, text_file.text
    assert text_file.json()['needs_ai'] is False
    assert '今天谈机器人' in text_file.json()['transcript']
    audio_file = client.post(
        '/api/v1/audio-studio/import-file',
        files={'file': ('episode.mp3', b'not-a-real-audio-file', 'audio/mpeg')},
    )
    assert audio_file.status_code == 200, audio_file.text
    assert audio_file.json()['needs_ai'] is True
    assert 'AI' in audio_file.json()['notice']


def test_audio_studio_skills_and_project_drafts_are_independent(client):
    assert client.get('/api/v1/audio-studio/status').json()['skills_configured'] is False
    skills = client.get('/api/v1/audio-studio/skills')
    assert skills.status_code == 200
    updated = {key: value + '\n团队规则。' for key, value in skills.json().items()}
    assert client.put('/api/v1/audio-studio/skills', json=updated).status_code == 200
    assert client.get('/api/v1/audio-studio/skills').json() == updated
    assert client.get('/api/v1/audio-studio/status').json()['skills_configured'] is True
    draft = {
        'title': '测试音频', 'source_kind': 'text', 'transcript': '原始文字',
        'cleaned': '清洗文字', 'simple': '简版', 'article_title': '',
        'article_summary': '', 'article_body': '',
    }
    created = client.post('/api/v1/audio-studio/projects', json=draft)
    assert created.status_code == 200, created.text
    saved = client.get('/api/v1/audio-studio/projects').json()['projects'][0]
    assert saved['title'] == '测试音频'
    saved['cleaned'] = '更新后的清洗文字'
    changed = client.put('/api/v1/audio-studio/projects/' + saved['id'], json=saved)
    assert changed.status_code == 200
    assert changed.json()['revision'] == 2


def test_audio_studio_process_requires_explicit_model_and_preserves_uncertainty(client, monkeypatch):
    import httpx, json
    from app.modules.atlas import audio_studio
    async def options(): return [{'id': 'chosen-model', 'name': 'Chosen'}]
    monkeypatch.setattr(audio_studio, 'model_options', options)
    monkeypatch.setattr(audio_studio, 'connection', lambda: ('secret', 'https://models.example/v1', 'test'))
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body['model'])
        if len(calls) == 1:
            payload = {'cleaned': '这家公司叫 [[?派森?]]。', 'uncertain': ['派森']}
        else:
            payload = {'simple': '一家机器人公司的访谈。'}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload, ensure_ascii=False)}}]})
    monkeypatch.setattr(audio_studio.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    missing = client.post('/api/v1/audio-studio/process', json={'model': 'missing', 'transcript': '原稿'})
    assert missing.status_code == 422
    result = client.post('/api/v1/audio-studio/process', json={'model': 'chosen-model', 'transcript': '原稿'})
    assert result.status_code == 200, result.text
    assert result.json()['cleaned'] == '这家公司叫 [[?派森?]]。'
    assert result.json()['uncertain'] == ['派森']
    assert calls == ['chosen-model', 'chosen-model']


def test_audio_studio_ai_correction_updates_cleaned_and_simple_only(client, monkeypatch):
    import httpx, json
    from app.modules.atlas import audio_studio
    async def options(): return [{'id': 'cheap-model', 'name': 'Cheap'}]
    monkeypatch.setattr(audio_studio, 'model_options', options)
    monkeypatch.setattr(audio_studio, 'connection', lambda: ('secret', 'https://models.example/v1', 'test'))
    original = httpx.AsyncClient
    def handler(request):
        payload = {'cleaned': '派资发布了新品。', 'simple': '派资新品。'}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload, ensure_ascii=False)}}]})
    monkeypatch.setattr(audio_studio.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = client.post('/api/v1/audio-studio/correct', json={
        'model': 'cheap-model', 'instruction': '所有派森都是派资',
        'cleaned': '派森发布了新品。', 'simple': '派森新品。',
    })
    assert result.status_code == 200, result.text
    assert set(result.json().values()) == {'派资发布了新品。', '派资新品。'}


def test_audio_studio_exports_a_feishu_document(client, monkeypatch):
    import httpx
    from app.modules.atlas import audio_studio
    monkeypatch.setenv('FEISHU_USER_ACCESS_TOKEN', 'user-token')
    monkeypatch.setenv('FEISHU_API_BASE', 'https://feishu.example/open-apis')
    monkeypatch.setenv('FEISHU_DOC_ORIGIN', 'https://geek.feishu.cn/docx')
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/docx/v1/documents'):
            assert request.headers['Authorization'] == 'Bearer user-token'
            return httpx.Response(200, json={'data': {'document': {'document_id': 'doc123'}}})
        return httpx.Response(200, json={'code': 0})
    monkeypatch.setattr(audio_studio.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = client.post('/api/v1/audio-studio/export-feishu', json={'title': '采访', 'content': '原版\n内容'})
    assert result.status_code == 200, result.text
    assert result.json()['url'] == 'https://geek.feishu.cn/docx/doc123'
    assert len(calls) == 2


def test_audio_studio_reads_private_feishu_minutes_as_user(client, monkeypatch):
    import httpx
    from app.modules.atlas import audio_studio
    monkeypatch.setenv('FEISHU_USER_ACCESS_TOKEN', 'user-token')
    monkeypatch.setenv('FEISHU_API_BASE', 'https://feishu.example/open-apis')
    original = httpx.AsyncClient
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer user-token'
        if request.url.path.endswith('/minutes/obcn123/transcript'):
            assert request.url.params['file_format'] == 'txt'
            return httpx.Response(200, text='张三 00:01\n这是妙记逐字稿。')
        return httpx.Response(200, json={'code': 0, 'data': {'minute': {'title': '用户的妙记'}}})
    monkeypatch.setattr(audio_studio.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = client.post('/api/v1/audio-studio/import-url', json={'url': 'https://geek.feishu.cn/minutes/obcn123?from=copy'})
    assert result.status_code == 200, result.text
    assert result.json()['title'] == '用户的妙记'
    assert '妙记逐字稿' in result.json()['transcript']
