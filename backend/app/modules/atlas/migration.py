"""One-time, non-destructive migration of legacy entities into the tag graph."""
import json

EDITORIAL_TAGS = (
    ('editorial:article', 'article', '文章', 'Articles'),
    ('editorial:podcast', 'podcast', '播客', 'Podcasts'),
    ('editorial:overseas', 'overseas-observation', '海外观察', 'Global observations'),
    ('editorial:conversations', 'conversations', '深度对话', 'Conversations'),
)

TOPIC_SEED = {
    ('robot-hardware','本体','Robot Hardware'): [('humanoid-robots','人形机器人','Humanoid Robots'),('dexterous-hands','灵巧手','Dexterous Hands'),('robotic-arms','机械臂','Robotic Arms'),('quadruped-robots','四足机器人','Quadruped Robots'),('novel-robot-forms','创新形态','Novel Robot Forms'),('motion-control','运动控制','Motion Control')],
    ('foundation-models','基础模型','Foundation Models'): [('vla','VLA','Vision-Language-Action Models'),('world-models','世界模型','World Models'),('post-training','后训练','Post-Training')],
    ('data','数据','Data'): [('data-collection','数据采集','Data Collection'),('real-world-data','真实世界数据','Real-World Data'),('simulation-synthetic-data','仿真与合成数据','Simulation & Synthetic Data')],
    ('deployment','落地','Deployment'): [('manufacturing','工业制造','Manufacturing'),('logistics-warehousing','物流仓储','Logistics & Warehousing'),('commercial-services','商业服务','Commercial Services'),('home-robotics','家庭场景','Home Robotics')],
}
COMPANY_SEED = [('unitree-robotics','宇树科技','Unitree Robotics'),('agibot','智元机器人','AgiBot'),('galbot','银河通用','Galbot'),('astribot','星尘智能','Astribot'),('x-square-robot','自变量机器人','X Square Robot'),('limx-dynamics','逐际动力','LimX Dynamics'),('fourier-intelligence','傅利叶智能','Fourier Intelligence'),('linkerbot','灵心巧手','Linkerbot'),('sharpa','Sharpa','Sharpa'),('dyna-robotics','Dyna Robotics','Dyna Robotics'),('figure-ai','Figure AI','Figure AI'),('physical-intelligence','Physical Intelligence','Physical Intelligence'),('skild-ai','Skild AI','Skild AI'),('1x-technologies','1X Technologies','1X Technologies')]


def ensure_editorial_tags(db, stamp):
    """Create hidden editorial filters and attach structural ones to old content."""
    db.execute('CREATE TABLE IF NOT EXISTS atlas_migrations (name TEXT PRIMARY KEY)')
    if db.execute("SELECT 1 FROM atlas_migrations WHERE name='editorial-tags-v1'").fetchone(): return
    for identifier, slug, zh, en in EDITORIAL_TAGS:
        data = dict(slug=slug, name_zh=zh, name_en=en, dimension='application', tag_type='content_type',
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

def classify_tags(db, stamp):
    """Upgrade legacy tag kinds without changing ids, links, or publications."""
    db.execute('CREATE TABLE IF NOT EXISTS atlas_migrations (name TEXT PRIMARY KEY)')
    if db.execute("SELECT 1 FROM atlas_migrations WHERE name='tag-kinds-v3'").fetchone(): return
    for row in db.execute('SELECT id,data FROM atlas_tags').fetchall():
        data = json.loads(row['data'])
        old = data.get('tag_type', 'topic')
        if row['id'].startswith('editorial:'):
            data['tag_type'] = 'content_type'
            data['map_visible'] = False
        elif old in ('company', 'product'):
            data['tag_type'] = 'entity'
            data['entity_kind'] = old
        else:
            data['tag_type'] = 'technical_topic'
        data.setdefault('featured_content_ids', [])
        db.execute('UPDATE atlas_tags SET data=?,revision=revision+1,updated_at=? WHERE id=?',
                   (json.dumps(data, ensure_ascii=False), stamp, row['id']))
    db.execute("INSERT INTO atlas_migrations VALUES ('tag-kinds-v3')")

def seed_initial_taxonomy(db, stamp):
    """Idempotently install the editorially approved starting taxonomy."""
    db.execute('CREATE TABLE IF NOT EXISTS atlas_migrations (name TEXT PRIMARY KEY)')
    if db.execute("SELECT 1 FROM atlas_migrations WHERE name='initial-taxonomy-v4'").fetchone(): return
    def insert(identifier, slug, zh, en, kind, entity_kind=None, map_visible=False, level='secondary'):
        existing = db.execute('SELECT id,data FROM atlas_tags WHERE id=? OR slug=?',(identifier,slug)).fetchone()
        if not existing and kind != 'content_type':
            for candidate in db.execute('SELECT id,data FROM atlas_tags').fetchall():
                value=json.loads(candidate['data'])
                if value.get('name_zh')==zh and (kind!='entity' or value.get('tag_type')=='entity'):
                    existing=candidate;break
        if existing:
            value=json.loads(existing['data'])
            value.update(tag_type=kind, entity_kind=entity_kind if kind=='entity' else None)
            value.setdefault('featured_content_ids',[])
            if not value.get('name_en'): value['name_en']=en
            db.execute('UPDATE atlas_tags SET data=?,updated_at=? WHERE id=?',(json.dumps(value,ensure_ascii=False),stamp,existing['id']))
            return existing['id']
        data=dict(slug=slug,name_zh=zh,name_en=en,dimension='technology',tag_type=kind,entity_kind=entity_kind,
                  map_visible=map_visible,map_level=level,visible_locales=['zh','en'],aliases=[],website='',
                  description_zh='',description_en='',parent_ids=[],related_tag_ids=[],featured_content_ids=[])
        db.execute('INSERT OR IGNORE INTO atlas_tags VALUES (?,?,?,?,?,?)',(identifier,slug,'technology',json.dumps(data,ensure_ascii=False),1,stamp))
        return identifier
    conversations=insert('editorial:conversations','conversations','深度对话','Conversations','content_type')
    for (slug,zh,en),children in TOPIC_SEED.items():
        parent=insert('topic:'+slug,slug,zh,en,'technical_topic',map_visible=True,level='primary')
        for child_slug,child_zh,child_en in children:
            child=insert('topic:'+child_slug,child_slug,child_zh,child_en,'technical_topic',map_visible=child_slug in {'humanoid-robots','dexterous-hands','vla','world-models','data-collection'},level='medium')
            db.execute("INSERT OR IGNORE INTO atlas_tag_relations VALUES (?,?,'parent')",(child,parent))
    entities={}
    for slug,zh,en in COMPANY_SEED:
        entities[slug]=insert('entity:'+slug,slug,zh,en,'entity','company')
    unitree=entities['unitree-robotics']
    for slug,zh,en in [('unitree-g1','G1','G1'),('unitree-h2','H2','H2')]:
        product=insert('entity:'+slug,slug,zh,en,'entity','product')
        db.execute("INSERT OR IGNORE INTO atlas_tag_relations VALUES (?,?,'parent')",(product,unitree))
    topic_ids={json.loads(r['data']).get('slug'):r['id'] for r in db.execute('SELECT id,data FROM atlas_tags')}
    for topic in (topic_ids.get('humanoid-robots'),topic_ids.get('motion-control')):
        if not topic: continue
        db.execute("INSERT OR IGNORE INTO atlas_tag_relations VALUES (?,?,'related')",(unitree,topic))
    # Keep legacy coarse categories editable and searchable, but avoid showing
    # them beside the new approved top-level taxonomy on the homepage map.
    for row in db.execute("SELECT id,data FROM atlas_tags WHERE id LIKE 'category:%'").fetchall():
        value=json.loads(row['data']);value['map_visible']=False
        db.execute('UPDATE atlas_tags SET data=?,updated_at=? WHERE id=?',(json.dumps(value,ensure_ascii=False),stamp,row['id']))
    # Retire old display-only filters by folding worldview into Conversations.
    for table,column in [('atlas_contents','data'),('atlas_publications','snapshot')]:
        for row in db.execute(f'SELECT rowid,{column} FROM {table}').fetchall():
            content=json.loads(row[column]); ids=content.get('tag_ids',[])
            if 'editorial:worldview' in ids and conversations not in ids:
                content['tag_ids']=ids+[conversations]
            content['tag_ids']=[x for x in content.get('tag_ids',[]) if x not in ('editorial:worldview','editorial:thinking')]
            if content['tag_ids'] != ids:
                db.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?',(json.dumps(content,ensure_ascii=False),row['rowid']))
                if table=='atlas_contents':
                    content_id=db.execute('SELECT id FROM atlas_contents WHERE rowid=?',(row['rowid'],)).fetchone()[0]
                    if conversations in content['tag_ids']:
                        db.execute('INSERT OR IGNORE INTO atlas_content_tags VALUES (?,?)',(content_id,conversations))
    db.execute("DELETE FROM atlas_content_tags WHERE tag_id IN ('editorial:worldview','editorial:thinking')")
    db.execute("DELETE FROM atlas_tag_relations WHERE source_id IN ('editorial:worldview','editorial:thinking') OR target_id IN ('editorial:worldview','editorial:thinking')")
    db.execute("DELETE FROM atlas_tags WHERE id IN ('editorial:worldview','editorial:thinking')")
    db.execute("INSERT INTO atlas_migrations VALUES ('initial-taxonomy-v4')")

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
