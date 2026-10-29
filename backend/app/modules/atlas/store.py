"""The independent InTheLoop catalogue. No legacy publishing calls."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from ...database import database

SCHEMA = '''
CREATE TABLE IF NOT EXISTS atlas_companies (
 id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS atlas_tags (
 id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, dimension TEXT NOT NULL,
 data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS atlas_tag_relations (
 source_id TEXT NOT NULL REFERENCES atlas_tags(id),
 target_id TEXT NOT NULL REFERENCES atlas_tags(id),
 relation TEXT NOT NULL CHECK(relation IN ('parent','related')),
 PRIMARY KEY(source_id,target_id,relation), CHECK(source_id <> target_id));
CREATE TABLE IF NOT EXISTS atlas_person_affiliations (
 person_id TEXT NOT NULL REFERENCES atlas_tags(id),
 company_id TEXT NOT NULL REFERENCES atlas_tags(id),
 relationship TEXT NOT NULL CHECK(relationship IN ('employment','founder','advisor','board','other')),
 is_primary INTEGER NOT NULL DEFAULT 1,
 title_zh TEXT NOT NULL DEFAULT '', title_en TEXT NOT NULL DEFAULT '',
 start_date TEXT NOT NULL DEFAULT '', end_date TEXT NOT NULL DEFAULT '',
 sort_order INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(person_id,company_id,relationship,start_date));
CREATE TABLE IF NOT EXISTS atlas_company_tags (
 company_id TEXT NOT NULL REFERENCES atlas_companies(id),
 tag_id TEXT NOT NULL REFERENCES atlas_tags(id), evidence_url TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '', verified_at TEXT NOT NULL,
 PRIMARY KEY(company_id,tag_id));
CREATE TABLE IF NOT EXISTS atlas_products (
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES atlas_companies(id),
 data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS atlas_contents (
 id TEXT PRIMARY KEY, data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS atlas_content_companies (
 content_id TEXT NOT NULL REFERENCES atlas_contents(id), company_id TEXT NOT NULL REFERENCES atlas_companies(id),
 PRIMARY KEY(content_id,company_id));
CREATE TABLE IF NOT EXISTS atlas_content_tags (
 content_id TEXT NOT NULL REFERENCES atlas_contents(id), tag_id TEXT NOT NULL REFERENCES atlas_tags(id),
 PRIMARY KEY(content_id,tag_id));
CREATE TABLE IF NOT EXISTS atlas_publications (
 content_id TEXT NOT NULL REFERENCES atlas_contents(id), locale TEXT NOT NULL,
 snapshot TEXT NOT NULL, published_at TEXT NOT NULL, revision INTEGER NOT NULL,
 PRIMARY KEY(content_id,locale));
CREATE TABLE IF NOT EXISTS atlas_ai_runs (
 id TEXT PRIMARY KEY, model TEXT NOT NULL, task TEXT NOT NULL, skill_version TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS atlas_settings (
 key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize():
    with database() as db:
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        from .migration import unify_tags, ensure_editorial_tags, classify_tags, seed_initial_taxonomy
        unify_tags(db, now())
        ensure_editorial_tags(db, now())
        if not db.execute("SELECT 1 FROM atlas_migrations WHERE name='tag-display-relations-v2'").fetchone():
            db.execute("INSERT OR IGNORE INTO atlas_tag_relations SELECT source_id,target_id,'related' FROM atlas_tag_relations WHERE relation='parent'")
            db.execute("DELETE FROM atlas_tag_relations WHERE relation='parent'")
            db.execute("INSERT INTO atlas_migrations VALUES ('tag-display-relations-v2')")
        classify_tags(db, now())
        seed_initial_taxonomy(db, now())
        migrate_person_affiliations(db)


def migrate_person_affiliations(db):
    """Upgrade the short-lived status-based draft schema without losing local data."""
    columns = {row['name'] for row in db.execute('PRAGMA table_info(atlas_person_affiliations)')}
    required = {'person_id','company_id','relationship','is_primary','title_zh','title_en','start_date','end_date','sort_order'}
    if required.issubset(columns):
        return
    db.execute('ALTER TABLE atlas_person_affiliations RENAME TO atlas_person_affiliations_legacy')
    db.execute('''CREATE TABLE atlas_person_affiliations (
        person_id TEXT NOT NULL REFERENCES atlas_tags(id),
        company_id TEXT NOT NULL REFERENCES atlas_tags(id),
        relationship TEXT NOT NULL CHECK(relationship IN ('employment','founder','advisor','board','other')),
        is_primary INTEGER NOT NULL DEFAULT 1,
        title_zh TEXT NOT NULL DEFAULT '', title_en TEXT NOT NULL DEFAULT '',
        start_date TEXT NOT NULL DEFAULT '', end_date TEXT NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(person_id,company_id,relationship,start_date))''')
    legacy = {row['name'] for row in db.execute('PRAGMA table_info(atlas_person_affiliations_legacy)')}
    if {'person_id','company_id'}.issubset(legacy):
        def value(name, fallback):
            return name if name in legacy else fallback
        db.execute(f'''INSERT OR IGNORE INTO atlas_person_affiliations
            SELECT person_id,company_id,{value('relationship', "'employment'")},{value('is_primary','1')},
                   {value('title_zh', "''")},{value('title_en', "''")},{value('start_date', "''")},
                   CASE WHEN {value('status', "'current'")}='former' THEN {value('end_date', "''")} ELSE '' END,
                   {value('sort_order','0')}
            FROM atlas_person_affiliations_legacy''')
    db.execute('DROP TABLE atlas_person_affiliations_legacy')


def records(db, kind):
    rows = db.execute(f'SELECT * FROM atlas_{kind} ORDER BY updated_at DESC').fetchall()
    result = []
    for row in rows:
        item = json.loads(row['data'])
        item.update(id=row['id'], revision=row['revision'], updated_at=row['updated_at'])
        if kind == 'companies':
            item['tag_links'] = [dict(x) for x in db.execute('SELECT tag_id,evidence_url,note,verified_at FROM atlas_company_tags WHERE company_id=?', (row['id'],))]
        if kind == 'tags':
            item.setdefault('map_visible', True)
            item.setdefault('map_level', 'secondary')
            item.setdefault('tag_type', 'technical_topic')
            item.setdefault('entity_kind', None)
            item.setdefault('visibility', 'public')
            item.setdefault('featured_content_ids', [])
            item.setdefault('aliases', [])
            item.setdefault('website', '')
            item['parent_ids'] = [r[0] for r in db.execute("SELECT target_id FROM atlas_tag_relations WHERE source_id=? AND relation='parent'", (row['id'],))]
            item['related_tag_ids'] = [r[0] for r in db.execute("SELECT target_id FROM atlas_tag_relations WHERE source_id=? AND relation='related' UNION SELECT source_id FROM atlas_tag_relations WHERE target_id=? AND relation='related'", (row['id'],row['id']))]
            item['affiliations'] = [dict(r) | {'is_primary': bool(r['is_primary']), 'status': 'former' if r['end_date'] else 'current'} for r in db.execute("SELECT company_id,relationship,is_primary,title_zh,title_en,start_date,end_date FROM atlas_person_affiliations WHERE person_id=? ORDER BY end_date='' DESC,is_primary DESC,sort_order", (row['id'],))]
        if kind == 'contents':
            item['publications'] = [dict(x) for x in db.execute('SELECT locale,published_at,revision FROM atlas_publications WHERE content_id=?', (row['id'],))]
        result.append(item)
    return result


def catalogue():
    initialize()
    with database() as db:
        result = {kind: records(db, kind) for kind in ('companies', 'tags', 'products', 'contents')}
        row = db.execute("SELECT value FROM atlas_settings WHERE key='homepage-featured'").fetchone()
        try: result['homepage_featured_ids'] = json.loads(row['value']) if row else []
        except (TypeError, json.JSONDecodeError): result['homepage_featured_ids'] = []
        return result


def get_setting(key, fallback=''):
    initialize()
    with database() as db:
        row = db.execute('SELECT value FROM atlas_settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else fallback


def set_setting(key, value):
    initialize()
    with database() as db:
        db.execute('INSERT INTO atlas_settings VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at', (key, value, now()))


def save(kind, data, record_id=None):
    initialize()
    record_id = record_id or str(uuid.uuid4())
    with database() as db:
        existing = db.execute(f'SELECT revision FROM atlas_{kind} WHERE id=?', (record_id,)).fetchone()
        expected = data.pop('revision', 0)
        if existing and expected != existing['revision']:
            raise ValueError('资料已被其他编辑更新，请重新打开后再保存')
        if not existing and expected:
            raise ValueError('资料不存在，请重新打开')
        revision = existing['revision'] + 1 if existing else 1
        links = data.pop('tag_links', []) if kind == 'companies' else []
        affiliations = data.pop('affiliations', []) if kind == 'tags' else []
        if kind == 'tags':
            parents = data.get('parent_ids', [])
            related = data.get('related_tag_ids', [])
            known = {r[0] for r in db.execute('SELECT id FROM atlas_tags')}
            if record_id in parents or record_id in related: raise ValueError('标签不能关联自己')
            if not set(parents + related).issubset(known): raise ValueError('关联的标签不存在')
            content_ids = {r[0] for r in db.execute('SELECT id FROM atlas_contents')}
            if not set(data.get('featured_content_ids', [])).issubset(content_ids): raise ValueError('精选内容不存在')
            tag_type = data.get('tag_type', 'technical_topic')
            if data.get('visibility', 'public') == 'internal': data['map_visible'] = False
            if tag_type == 'content_type':
                data['map_visible'] = False
                if parents: raise ValueError('内容类型不设置上级；它在中文首页筛选区显示')
                if related: raise ValueError('内容类型不与公司或技术主题建立资料库关系')
            parent_data = {r['id']: json.loads(r['data']) for r in db.execute('SELECT id,data FROM atlas_tags') if r['id'] in parents}
            related_data = {r['id']: json.loads(r['data']) for r in db.execute('SELECT id,data FROM atlas_tags') if r['id'] in related}
            def normalized(value):
                kind = value.get('tag_type', 'technical_topic')
                return 'technical_topic' if kind == 'topic' else 'entity' if kind in ('company','product') else kind
            if tag_type == 'technical_topic' and any(normalized(x) != 'technical_topic' for x in parent_data.values()):
                raise ValueError('技术主题的上级也必须是技术主题')
            if tag_type == 'entity' and data.get('entity_kind') == 'company' and parents:
                raise ValueError('公司是实体顶层；只有产品选择所属公司')
            if tag_type == 'entity' and data.get('entity_kind') == 'product' and any(
                normalized(x) != 'entity' or x.get('entity_kind', x.get('tag_type')) not in ('company',) for x in parent_data.values()):
                raise ValueError('产品的上级必须是公司')
            if tag_type == 'entity' and data.get('entity_kind') == 'person' and parents:
                raise ValueError('人物任职关系请使用当前公司 / 前公司，不使用父级标签')
            if tag_type == 'entity' and data.get('entity_kind') in ('company','product') and any(normalized(x) != 'technical_topic' for x in related_data.values()):
                raise ValueError('公司和产品只关联技术主题，不关联内容类型')
            if any(normalized(x) == 'content_type' for x in related_data.values()):
                raise ValueError('内容类型不参与标签之间的资料库关系')
            if tag_type == 'entity' and data.get('entity_kind') == 'person' and related:
                raise ValueError('人物与公司的关系请使用任职经历')
            company_ids = {r['id'] for r in db.execute('SELECT id,data FROM atlas_tags') if (lambda x: x.get('tag_type') == 'entity' and x.get('entity_kind') == 'company')(json.loads(r['data']))}
            if data.get('entity_kind') == 'person' and not {a.get('company_id') for a in affiliations}.issubset(company_ids):
                raise ValueError('人物任职经历引用了不存在的公司')
            graph = {}
            for r in db.execute("SELECT source_id,target_id FROM atlas_tag_relations WHERE relation='parent'"):
                graph.setdefault(r[0], []).append(r[1])
            graph[record_id] = parents
            todo, seen = list(parents), set()
            while todo:
                current = todo.pop()
                if current == record_id: raise ValueError('上级标签不能形成循环；普通相关标签可以交叉关联')
                if current not in seen:
                    seen.add(current)
                    todo.extend(graph.get(current, []))
        if kind == 'contents':
            automatic = ['editorial:podcast' if data.get('kind') == 'podcast' else 'editorial:article']
            if data.get('section') == 'overseas': automatic.append('editorial:overseas')
            structural = {'editorial:article', 'editorial:podcast', 'editorial:overseas'}
            data['tag_ids'] = [tag_id for tag_id in data.get('tag_ids', []) if tag_id not in structural] + automatic
        stamp = now()
        payload = json.dumps(data, ensure_ascii=False)
        extra = {'slug': data['slug']} if kind in ('companies', 'tags') else {}
        if kind == 'tags': extra['dimension'] = data['dimension']
        if kind == 'products': extra['company_id'] = data['company_id']
        columns = ['id', 'data', 'revision', 'updated_at', *extra]
        values = [record_id, payload, revision, stamp, *extra.values()]
        updates = ','.join(f'{c}=excluded.{c}' for c in columns if c != 'id')
        db.execute(f"INSERT INTO atlas_{kind} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(id) DO UPDATE SET {updates}", values)
        if kind == 'tags':
            old_related = {r[0] for r in db.execute("SELECT target_id FROM atlas_tag_relations WHERE source_id=? AND relation='related' UNION SELECT source_id FROM atlas_tag_relations WHERE target_id=? AND relation='related'", (record_id,record_id))}
            for affected in old_related.symmetric_difference(set(data.get('related_tag_ids', []))):
                db.execute('UPDATE atlas_tags SET revision=revision+1,updated_at=? WHERE id=?', (stamp,affected))
            db.execute("DELETE FROM atlas_tag_relations WHERE source_id=? OR (target_id=? AND relation='related')", (record_id,record_id))
            for relation, ids in [('parent', data.get('parent_ids', [])), ('related', data.get('related_tag_ids', []))]:
                for target in ids:
                    db.execute('INSERT INTO atlas_tag_relations VALUES (?,?,?)', (record_id,target,relation))
            db.execute('DELETE FROM atlas_person_affiliations WHERE person_id=?', (record_id,))
            if data.get('tag_type') == 'entity' and data.get('entity_kind') == 'person':
                for order, item in enumerate(affiliations):
                    db.execute('INSERT INTO atlas_person_affiliations VALUES (?,?,?,?,?,?,?,?,?)', (record_id,item['company_id'],item.get('relationship','employment'),1 if item.get('is_primary',True) else 0,item.get('title_zh',''),item.get('title_en',''),item.get('start_date',''),item.get('end_date',''),order))
        if kind == 'companies':
            db.execute('DELETE FROM atlas_company_tags WHERE company_id=?', (record_id,))
            for link in links:
                db.execute('INSERT INTO atlas_company_tags VALUES (?,?,?,?,?)', (record_id, link['tag_id'], link['evidence_url'], link['note'], link.get('verified_at') or stamp))
        if kind == 'contents':
            if data.get('visibility') == 'internal': db.execute("DELETE FROM atlas_publications WHERE content_id=?", (record_id,))
            elif data.get('section') == 'overseas' or data.get('chinese_only'): db.execute("DELETE FROM atlas_publications WHERE content_id=? AND locale='en'", (record_id,))
            for entity in ('companies', 'tags'):
                singular = 'company' if entity == 'companies' else 'tag'
                db.execute(f'DELETE FROM atlas_content_{entity} WHERE content_id=?', (record_id,))
                for related in data[f'{singular}_ids']:
                    db.execute(f'INSERT INTO atlas_content_{entity} VALUES (?,?)', (record_id, related))
        if kind == 'products':
            valid = {r[0] for r in db.execute('SELECT id FROM atlas_tags')}
            if not set(data['tag_ids']).issubset(valid): raise ValueError('产品引用了不存在的标签')
    return {'id': record_id, 'revision': revision}


def publish(content_id, locale, revision):
    initialize()
    with database() as db:
        row = db.execute('SELECT * FROM atlas_contents WHERE id=?', (content_id,)).fetchone()
        if not row: raise ValueError('内容不存在')
        if revision != row['revision']: raise ValueError('草稿版本已经改变，请重新预览')
        item = json.loads(row['data'])
        if item.get('visibility', 'public') == 'internal': raise ValueError('内部内容不能发布到官网')
        if locale == 'en' and item.get('section') == 'overseas': raise ValueError('海外观察仅发布到中文官网')
        if locale == 'en' and item.get('chinese_only'): raise ValueError('这条中文播客仅发布到中文官网')
        version = item['versions'].get(locale)
        if not version or not version['title'].strip(): raise ValueError('请先填写该语言标题')
        if version.get('destination') == 'external':
            if not (version.get('external_url') or item['source_url']): raise ValueError('请填写跳转链接')
        elif not version['body'].strip(): raise ValueError('在本站阅读的版本需要填写正文；如仅展示链接，请选择跳转到原平台')
        if locale == 'en' and item['kind'] == 'podcast' and not version['summary'].strip():
            raise ValueError('英文展示中文播客时，请先填写英文摘要')
        snapshot = {**item, 'versions': {locale: version}, 'id': content_id}
        db.execute('INSERT INTO atlas_publications VALUES (?,?,?,?,?) ON CONFLICT(content_id,locale) DO UPDATE SET snapshot=excluded.snapshot,published_at=excluded.published_at,revision=excluded.revision', (content_id, locale, json.dumps(snapshot, ensure_ascii=False), now(), revision))
    return {'ok': True}


def public_catalogue(locale):
    data = catalogue()
    companies = [c for c in data['companies'] if locale in c['visible_locales']]
    tags = [t for t in data['tags'] if t.get('visibility','public') == 'public' and locale in t['visible_locales']]
    tag_ids = {t['id'] for t in tags}
    company_ids = {c['id'] for c in companies}
    tags = [{**t, 'parent_ids': [i for i in t.get('parent_ids', []) if i in tag_ids], 'related_tag_ids': [i for i in t.get('related_tag_ids', []) if i in tag_ids], 'affiliations': [a for a in t.get('affiliations', []) if a.get('company_id') in tag_ids]} for t in tags]
    # Editorial evidence stays in the workbench; only confirmed visible relationships leave it.
    companies = [{k: v for k, v in c.items() if k != 'tag_links'} | {'tag_ids': [l['tag_id'] for l in c['tag_links'] if l['tag_id'] in tag_ids]} for c in companies]
    with database() as db:
        contents = []
        for row in db.execute('SELECT snapshot,published_at FROM atlas_publications WHERE locale=?', (locale,)):
            c = json.loads(row['snapshot'])
            if c.get('visibility','public') == 'internal': continue
            if locale == 'en' and (c.get('section') == 'overseas' or c.get('chinese_only')): continue
            c['company_ids'] = [i for i in c['company_ids'] if i in company_ids]
            c['tag_ids'] = [i for i in c['tag_ids'] if i in tag_ids]
            c['published_at'] = row['published_at']
            contents.append(c)
    contents.sort(key=lambda c: c['date'], reverse=True)
    published_ids = {c['id'] for c in contents}
    return {'companies': companies, 'tags': tags, 'contents': contents,
            'products': [p for p in data['products'] if p['company_id'] in company_ids and locale in p['visible_locales']],
            'homepage_featured_ids': [i for i in data.get('homepage_featured_ids', []) if i in published_ids]}
