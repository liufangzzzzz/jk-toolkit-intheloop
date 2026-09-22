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
CREATE TABLE IF NOT EXISTS atlas_audio_projects (
 id TEXT PRIMARY KEY, data TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_atlas_audio_projects_updated
 ON atlas_audio_projects(updated_at DESC);
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize():
    with database() as db:
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        from .migration import unify_tags, ensure_editorial_tags
        unify_tags(db, now())
        ensure_editorial_tags(db, now())
        if not db.execute("SELECT 1 FROM atlas_migrations WHERE name='tag-display-relations-v2'").fetchone():
            db.execute("INSERT OR IGNORE INTO atlas_tag_relations SELECT source_id,target_id,'related' FROM atlas_tag_relations WHERE relation='parent'")
            db.execute("DELETE FROM atlas_tag_relations WHERE relation='parent'")
            db.execute("INSERT INTO atlas_migrations VALUES ('tag-display-relations-v2')")


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
            item.setdefault('tag_type', 'topic')
            item.setdefault('aliases', [])
            item.setdefault('website', '')
            item['parent_ids'] = [r[0] for r in db.execute("SELECT target_id FROM atlas_tag_relations WHERE source_id=? AND relation='parent'", (row['id'],))]
            item['related_tag_ids'] = [r[0] for r in db.execute("SELECT target_id FROM atlas_tag_relations WHERE source_id=? AND relation='related' UNION SELECT source_id FROM atlas_tag_relations WHERE target_id=? AND relation='related'", (row['id'],row['id']))]
        if kind == 'contents':
            item['publications'] = [dict(x) for x in db.execute('SELECT locale,published_at,revision FROM atlas_publications WHERE content_id=?', (row['id'],))]
        result.append(item)
    return result


def catalogue():
    initialize()
    with database() as db:
        return {kind: records(db, kind) for kind in ('companies', 'tags', 'products', 'contents')}


def get_setting(key, fallback=''):
    initialize()
    with database() as db:
        row = db.execute('SELECT value FROM atlas_settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else fallback


def set_setting(key, value):
    initialize()
    with database() as db:
        db.execute('INSERT INTO atlas_settings VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at', (key, value, now()))


def audio_projects():
    initialize()
    with database() as db:
        return [json.loads(row['data']) | {'id': row['id'], 'revision': row['revision'], 'updated_at': row['updated_at']}
                for row in db.execute('SELECT * FROM atlas_audio_projects ORDER BY updated_at DESC')]


def save_audio_project(data, record_id=None):
    initialize()
    record_id = record_id or str(uuid.uuid4())
    with database() as db:
        row = db.execute('SELECT revision FROM atlas_audio_projects WHERE id=?', (record_id,)).fetchone()
        expected = int(data.pop('revision', 0) or 0)
        if row and row['revision'] != expected:
            raise ValueError('工作稿已被更新，请重新打开后再保存')
        revision = row['revision'] + 1 if row else 1
        stamp = now()
        db.execute(
            'INSERT INTO atlas_audio_projects VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,revision=excluded.revision,updated_at=excluded.updated_at',
            (record_id, json.dumps(data, ensure_ascii=False), revision, stamp),
        )
    return {'id': record_id, 'revision': revision, 'updated_at': stamp}


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
        if kind == 'tags':
            parents = data.get('parent_ids', [])
            related = data.get('related_tag_ids', [])
            known = {r[0] for r in db.execute('SELECT id FROM atlas_tags')}
            if record_id in parents or record_id in related: raise ValueError('标签不能关联自己')
            if not set(parents + related).issubset(known): raise ValueError('关联的标签不存在')
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
        if kind == 'companies':
            db.execute('DELETE FROM atlas_company_tags WHERE company_id=?', (record_id,))
            for link in links:
                db.execute('INSERT INTO atlas_company_tags VALUES (?,?,?,?,?)', (record_id, link['tag_id'], link['evidence_url'], link['note'], link.get('verified_at') or stamp))
        if kind == 'contents':
            if data.get('section') == 'overseas' or data.get('chinese_only'): db.execute("DELETE FROM atlas_publications WHERE content_id=? AND locale='en'", (record_id,))
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
    tags = [t for t in data['tags'] if locale in t['visible_locales']]
    tag_ids = {t['id'] for t in tags}
    company_ids = {c['id'] for c in companies}
    tags = [{**t, 'parent_ids': [i for i in t.get('parent_ids', []) if i in tag_ids], 'related_tag_ids': [i for i in t.get('related_tag_ids', []) if i in tag_ids]} for t in tags]
    # Editorial evidence stays in the workbench; only confirmed visible relationships leave it.
    companies = [{k: v for k, v in c.items() if k != 'tag_links'} | {'tag_ids': [l['tag_id'] for l in c['tag_links'] if l['tag_id'] in tag_ids]} for c in companies]
    with database() as db:
        contents = []
        for row in db.execute('SELECT snapshot,published_at FROM atlas_publications WHERE locale=?', (locale,)):
            c = json.loads(row['snapshot'])
            if locale == 'en' and (c.get('section') == 'overseas' or c.get('chinese_only')): continue
            c['company_ids'] = [i for i in c['company_ids'] if i in company_ids]
            c['tag_ids'] = [i for i in c['tag_ids'] if i in tag_ids]
            c['published_at'] = row['published_at']
            contents.append(c)
    contents.sort(key=lambda c: c['date'], reverse=True)
    return {'companies': companies, 'tags': tags, 'contents': contents,
            'products': [p for p in data['products'] if p['company_id'] in company_ids and locale in p['visible_locales']]}
