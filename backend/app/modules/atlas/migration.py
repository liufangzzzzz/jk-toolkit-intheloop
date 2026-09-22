"""One-time, non-destructive migration of legacy entities into the tag graph."""
import json

EDITORIAL_TAGS = (
    ('editorial:article', 'article', '文章', 'Articles'),
    ('editorial:podcast', 'podcast', '播客', 'Podcasts'),
    ('editorial:worldview', 'entrepreneurial-worldview', '创业世界观', 'Entrepreneurial worldview'),
    ('editorial:thinking', 'frontier-thinking', '前沿思考', 'Frontier thinking'),
    ('editorial:overseas', 'overseas-observation', '海外观察', 'Global observations'),
)


def ensure_editorial_tags(db, stamp):
    """Create hidden editorial filters and attach structural ones to old content."""
    db.execute('CREATE TABLE IF NOT EXISTS atlas_migrations (name TEXT PRIMARY KEY)')
    if db.execute("SELECT 1 FROM atlas_migrations WHERE name='editorial-tags-v1'").fetchone(): return
    for identifier, slug, zh, en in EDITORIAL_TAGS:
        data = dict(slug=slug, name_zh=zh, name_en=en, dimension='application', tag_type='topic',
                    map_visible=False, map_level='primary', visible_locales=['zh'], aliases=[], website='',
                    description_zh='', description_en='', parent_ids=[], related_tag_ids=[])
        db.execute('INSERT OR IGNORE INTO atlas_tags VALUES (?,?,?,?,?,?)',
                   (identifier, slug, 'application', json.dumps(data, ensure_ascii=False), 1, stamp))
    for table, column in [('atlas_contents', 'data'), ('atlas_publications', 'snapshot')]:
        for row in db.execute(f'SELECT rowid,{column} FROM {table}').fetchall():
            content = json.loads(row[column])
            automatic = ['editorial:podcast' if content.get('kind') == 'podcast' else 'editorial:article']
            if content.get('section') == 'overseas': automatic.append('editorial:overseas')
            content['tag_ids'] = list(dict.fromkeys(content.get('tag_ids', []) + automatic))
            db.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?', (json.dumps(content, ensure_ascii=False), row['rowid']))
            if table == 'atlas_contents':
                content_id = db.execute('SELECT id FROM atlas_contents WHERE rowid=?', (row['rowid'],)).fetchone()[0]
                for tag_id in automatic:
                    db.execute('INSERT OR IGNORE INTO atlas_content_tags VALUES (?,?)', (content_id, tag_id))
    db.execute("INSERT INTO atlas_migrations VALUES ('editorial-tags-v1')")

def unify_tags(db, stamp):
    db.execute('CREATE TABLE IF NOT EXISTS atlas_migrations (name TEXT PRIMARY KEY)')
    if db.execute("SELECT 1 FROM atlas_migrations WHERE name='unified-tags-v1'").fetchone(): return
    old_tags = list(db.execute('SELECT * FROM atlas_tags'))
    names = {'form':('机器人本体','Robot bodies'),'technology':('机器人大脑','Robot intelligence'),'value_chain':('数据与部件','Data & components'),'application':('应用','Applications')}
    def insert(identifier, data):
        db.execute('INSERT OR IGNORE INTO atlas_tags VALUES (?,?,?,?,?,?)',(identifier,data['slug'],data.get('dimension','technology'),json.dumps(data,ensure_ascii=False),1,stamp))
    for dim in {r['dimension'] for r in old_tags}:
        zh,en=names[dim]
        insert('category:'+dim,dict(slug='category-'+dim,name_zh=zh,name_en=en,dimension=dim,tag_type='topic',map_visible=True,map_level='primary',visible_locales=['zh','en'],description_zh='',description_en=''))
    for row in old_tags:
        db.execute("INSERT OR IGNORE INTO atlas_tag_relations VALUES (?,?,'parent')",(row['id'],'category:'+row['dimension']))
    mapping={}
    for row in db.execute('SELECT * FROM atlas_companies').fetchall():
        c=json.loads(row['data']); identifier='company:'+row['id'];mapping[row['id']]=identifier
        insert(identifier,dict(slug='company-'+c['slug'],name_zh=c['name_zh'],name_en=c.get('name_en',''),dimension='technology',tag_type='company',map_visible=c.get('map_visible',False),map_level='secondary',visible_locales=c.get('visible_locales',[]),website=c.get('website',''),aliases=c.get('aliases',[]),description_zh=c.get('summary_zh',''),description_en=c.get('summary_en','')))
        for link in db.execute('SELECT tag_id FROM atlas_company_tags WHERE company_id=?',(row['id'],)):
            db.execute("INSERT OR IGNORE INTO atlas_tag_relations VALUES (?,?,'related')",(identifier,link[0]))
    for row in db.execute('SELECT * FROM atlas_products').fetchall():
        c=json.loads(row['data']);identifier='product:'+row['id']
        insert(identifier,dict(slug='product-'+row['id'],name_zh=c['name_zh'],name_en=c.get('name_en',''),dimension='form',tag_type='product',map_visible=False,map_level='secondary',visible_locales=c.get('visible_locales',[]),description_zh=c.get('summary_zh',''),description_en=c.get('summary_en','')))
        for target in [*c.get('tag_ids',[]),mapping.get(c['company_id'])]:
            if target:db.execute("INSERT OR IGNORE INTO atlas_tag_relations VALUES (?,?,'related')",(identifier,target))
    for table,column in [('atlas_contents','data'),('atlas_publications','snapshot')]:
        for row in db.execute(f'SELECT rowid,{column} FROM {table}').fetchall():
            c=json.loads(row[column]); extra=[mapping[i] for i in c.get('company_ids',[]) if i in mapping]
            c['tag_ids']=list(dict.fromkeys(c.get('tag_ids',[])+extra))
            db.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?',(json.dumps(c,ensure_ascii=False),row['rowid']))
            if table=='atlas_contents':
                content_id=db.execute('SELECT id FROM atlas_contents WHERE rowid=?',(row['rowid'],)).fetchone()[0]
                for tag in extra:db.execute('INSERT OR IGNORE INTO atlas_content_tags VALUES (?,?)',(content_id,tag))
    db.execute("INSERT INTO atlas_migrations VALUES ('unified-tags-v1')")
