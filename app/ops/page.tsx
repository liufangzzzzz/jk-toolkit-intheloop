'use client';

import { ChangeEvent, FormEvent, useEffect, useState } from 'react';

type Tool = 'wechat' | 'website';
type BusyState = '' | 'saving' | 'testing' | 'parsing' | 'draft' | 'publishing' | 'connecting';

type WechatBlock = {
  type: 'paragraph' | 'heading' | 'question' | 'answer' | 'image' | 'caption' | 'file';
  content: string;
  speaker: string;
  url?: string | null;
  caption?: string | null;
  source_block_id: string;
};

type WechatArticle = {
  title: string;
  author: string;
  editor: string;
  digest: string;
  header_source: string;
  blocks: WechatBlock[];
  warnings: string[];
  video_count: number;
  attachment_count: number;
};

type WechatParseResult = {
  article: WechatArticle;
  preview_html: string;
  stats: { heading_count: number; image_count: number; video_count: number };
  warnings: string[];
};

type WechatSettings = {
  app_id: string;
  has_secret: boolean;
  account_name: string;
  tested: boolean;
};

type WebsiteArticle = {
  title: string;
  abstract: string;
  content_html: string;
  tags: string[];
  cover_asset: string;
  source_type: 'wechat_url' | 'docx' | 'doc';
  source_ref: string;
  warnings: string[];
};

type WebsiteParseResult = {
  article: WebsiteArticle;
  preview_html: string;
};

type WebsiteStatus = {
  connected: boolean;
  fixed_credentials: boolean;
  nickname: string;
  author_id: number | string | null;
  column_id: number;
  columns: Array<{ id: number; title: string }>;
};

type PublishResult = {
  ok: boolean;
  media_id?: string;
  article_id?: number | string;
  public_url?: string;
  admin_edit_url?: string;
  state?: string;
  warnings?: string[];
  duplicate_prevented?: boolean;
};

function requestId(prefix: string): string {
  const id = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${id}`;
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
    credentials: 'include',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    const message = typeof detail === 'string' ? detail : detail?.message;
    throw new Error(message || '请求失败');
  }
  return payload as T;
}

export default function OperationsWorkbench() {
  const [tool, setTool] = useState<Tool>('wechat');
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [backendConnected, setBackendConnected] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(true);
  const [setupRequired, setSetupRequired] = useState(false);
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);

  const [wechatSettings, setWechatSettings] = useState<WechatSettings | null>(null);
  const [wechatAppId, setWechatAppId] = useState('');
  const [wechatSecret, setWechatSecret] = useState('');
  const [wechatName, setWechatName] = useState('In The Loop.具身现场');
  const [wechatBusy, setWechatBusy] = useState<BusyState>('');
  const [wechatNotice, setWechatNotice] = useState('');
  const [feishuUrl, setFeishuUrl] = useState('');
  const [wechatParsed, setWechatParsed] = useState<WechatParseResult | null>(null);
  const [wechatRequestId, setWechatRequestId] = useState('');

  const [websiteStatus, setWebsiteStatus] = useState<WebsiteStatus | null>(null);
  const [websiteSource, setWebsiteSource] = useState<'url' | 'word'>('url');
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [wordFile, setWordFile] = useState<File | null>(null);
  const [websiteBusy, setWebsiteBusy] = useState<BusyState>('');
  const [websiteNotice, setWebsiteNotice] = useState('');
  const [websiteParsed, setWebsiteParsed] = useState<WebsiteParseResult | null>(null);
  const [websiteRequestId, setWebsiteRequestId] = useState('');
  const [selectedColumn, setSelectedColumn] = useState(0);
  const [websitePublishResult, setWebsitePublishResult] = useState<PublishResult | null>(null);

  useEffect(() => {
    api<{ authenticated: boolean; auth_enabled: boolean; setup_required?: boolean }>('/auth/me')
      .then((status) => {
        setBackendConnected(true);
        setAuthenticated(status.authenticated);
        setAuthEnabled(status.auth_enabled);
        setSetupRequired(Boolean(status.setup_required));
      })
      .catch(() => {
        setBackendConnected(false);
        setAuthenticated(false);
      })
      .finally(() => setCheckingAuth(false));
  }, []);

  useEffect(() => {
    if (!authenticated || !backendConnected) return;
    void loadWechatSettings();
    void loadWebsiteStatus();
  }, [authenticated, backendConnected]);

  async function loadWechatSettings() {
    try {
      const next = await api<WechatSettings>('/wechat-draft/settings');
      setWechatSettings(next);
      setWechatAppId(next.app_id);
      setWechatName(next.account_name);
    } catch {
      setWechatSettings(null);
    }
  }

  async function loadWebsiteStatus() {
    try {
      const next = await api<WebsiteStatus>('/website-import/status');
      setWebsiteStatus(next);
      setSelectedColumn(next.column_id || next.columns[0]?.id || 0);
    } catch {
      setWebsiteStatus(null);
    }
  }

  async function login(event: FormEvent) {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError('');
    try {
      const path = setupRequired ? '/auth/setup' : '/auth/login';
      const body = setupRequired ? { password } : { password, scope: 'intheloop' };
      const status = await api<{ authenticated: boolean; auth_enabled: boolean; setup_required?: boolean }>(path, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setBackendConnected(true);
      setAuthenticated(status.authenticated);
      setAuthEnabled(status.auth_enabled);
      setSetupRequired(Boolean(status.setup_required));
      setPassword('');
    } catch (failure) {
      setLoginError(
        backendConnected
          ? failure instanceof Error ? failure.message : '登录失败'
          : '后端服务没有启动，当前页面不能执行解析或发布。',
      );
    } finally {
      setLoginBusy(false);
    }
  }

  async function logout() {
    await api('/auth/logout', { method: 'POST' }).catch(() => undefined);
    setAuthenticated(false);
    setWechatParsed(null);
    setWebsiteParsed(null);
  }

  async function saveWechatSettings() {
    setWechatBusy('saving');
    setWechatNotice('');
    try {
      const next = await api<WechatSettings>('/wechat-draft/settings', {
        method: 'PUT',
        body: JSON.stringify({
          app_id: wechatAppId.trim(),
          app_secret: wechatSecret,
          account_name: wechatName.trim(),
        }),
      });
      setWechatSettings(next);
      setWechatSecret('');
      setWechatNotice('公众号配置已保存，请检测连接。');
    } catch (failure) {
      setWechatNotice(failure instanceof Error ? failure.message : '保存失败');
    } finally {
      setWechatBusy('');
    }
  }

  async function testWechatConnection() {
    setWechatBusy('testing');
    setWechatNotice('');
    try {
      const result = await api<{ message: string }>('/wechat-draft/settings/test', { method: 'POST' });
      await loadWechatSettings();
      setWechatNotice(result.message);
    } catch (failure) {
      setWechatNotice(failure instanceof Error ? failure.message : '检测失败');
    } finally {
      setWechatBusy('');
    }
  }

  async function parseFeishuDocument() {
    if (!feishuUrl.trim()) return;
    setWechatBusy('parsing');
    setWechatNotice('');
    setWechatParsed(null);
    try {
      const parsed = await api<WechatParseResult>('/wechat-draft/parse', {
        method: 'POST',
        body: JSON.stringify({ feishu_url: feishuUrl.trim() }),
      });
      setWechatParsed(parsed);
      setWechatRequestId(requestId('wechat'));
    } catch (failure) {
      setWechatNotice(failure instanceof Error ? failure.message : '飞书文档解析失败');
    } finally {
      setWechatBusy('');
    }
  }

  async function createWechatDraft() {
    if (!wechatParsed) return;
    setWechatBusy('draft');
    setWechatNotice('');
    try {
      const result = await api<PublishResult>('/wechat-draft/publish', {
        method: 'POST',
        body: JSON.stringify({
          article: wechatParsed.article,
          request_id: wechatRequestId,
          source_ref: feishuUrl.trim(),
        }),
      });
      setWechatNotice(`微信草稿创建成功${result.media_id ? `，Media ID：${result.media_id}` : ''}${result.duplicate_prevented ? '（已阻止重复提交）' : ''}`);
    } catch (failure) {
      setWechatNotice(failure instanceof Error ? failure.message : '微信草稿创建失败');
    } finally {
      setWechatBusy('');
    }
  }

  async function connectWebsite() {
    setWebsiteBusy('connecting');
    setWebsiteNotice('');
    try {
      const next = await api<WebsiteStatus>('/website-import/connect', { method: 'POST' });
      setWebsiteStatus(next);
      setSelectedColumn(next.column_id || next.columns[0]?.id || 0);
      setWebsiteNotice(`官网账号连接成功${next.nickname ? `：${next.nickname}` : ''}`);
    } catch (failure) {
      setWebsiteNotice(failure instanceof Error ? failure.message : '官网连接失败');
    } finally {
      setWebsiteBusy('');
    }
  }

  function acceptWordFile(event: ChangeEvent<HTMLInputElement>) {
    setWordFile(event.target.files?.[0] || null);
    setWebsiteNotice('');
  }

  async function parseWebsiteSource() {
    if (websiteSource === 'url' && !websiteUrl.trim()) return;
    if (websiteSource === 'word' && !wordFile) return;
    setWebsiteBusy('parsing');
    setWebsiteNotice('');
    setWebsiteParsed(null);
    setWebsitePublishResult(null);
    try {
      let parsed: WebsiteParseResult;
      if (websiteSource === 'url') {
        parsed = await api<WebsiteParseResult>('/website-import/parse-url', {
          method: 'POST',
          body: JSON.stringify({ source_url: websiteUrl.trim() }),
        });
      } else {
        const form = new FormData();
        form.set('file', wordFile as File);
        parsed = await api<WebsiteParseResult>('/website-import/parse-file', {
          method: 'POST',
          body: form,
        });
      }
      setWebsiteParsed(parsed);
      setWebsiteRequestId(requestId('website'));
    } catch (failure) {
      setWebsiteNotice(failure instanceof Error ? failure.message : '内容解析失败');
    } finally {
      setWebsiteBusy('');
    }
  }

  function updateWebsiteArticle(patch: Partial<WebsiteArticle>) {
    setWebsiteParsed((current) => current
      ? { ...current, article: { ...current.article, ...patch } }
      : current);
  }

  async function publishWebsite(mode: 'draft' | 'publish') {
    if (!websiteParsed) return;
    if (mode === 'publish') {
      const confirmed = window.confirm(`确认直接发布《${websiteParsed.article.title}》到极客公园官网吗？发布后文章会立即进入线上状态。`);
      if (!confirmed) return;
    }
    setWebsiteBusy(mode === 'draft' ? 'draft' : 'publishing');
    setWebsiteNotice('');
    setWebsitePublishResult(null);
    try {
      const result = await api<PublishResult>('/website-import/publish', {
        method: 'POST',
        body: JSON.stringify({
          article: websiteParsed.article,
          mode,
          column_id: selectedColumn || null,
          request_id: `${websiteRequestId}:${mode}`,
        }),
      });
      setWebsitePublishResult(result);
      setWebsiteNotice(`${mode === 'publish' ? '官网文章已发布' : '官网草稿已创建'}${result.duplicate_prevented ? '（已阻止重复提交）' : ''}`);
      await loadWebsiteStatus();
    } catch (failure) {
      setWebsiteNotice(failure instanceof Error ? failure.message : '官网写入失败');
    } finally {
      setWebsiteBusy('');
    }
  }

  if (checkingAuth) {
    return <main className="loading-screen"><span className="wordmark-mini">ITL</span><p>正在打开运营工作台</p></main>;
  }

  const locked = setupRequired || (authEnabled && !authenticated);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="wordmark-mini">ITL</span>
          <span><strong>In The Loop</strong><small>运营工作台</small></span>
        </div>
        {!locked && (
          <nav className="tool-tabs" aria-label="运营工具">
            <button className={tool === 'wechat' ? 'active' : ''} onClick={() => setTool('wechat')}>公众号草稿</button>
            <button className={tool === 'website' ? 'active' : ''} onClick={() => setTool('website')}>极客公园官网</button>
          </nav>
        )}
        <div className="topbar-actions">
          <span className="mode-label">INTERNAL</span>
          {authEnabled && authenticated && <button className="text-button" onClick={logout}>退出</button>}
        </div>
      </header>

      {locked ? (
        <section className="access-stage">
          <div className="access-brand" aria-label="In The Loop">
            <div className="access-wordmark" aria-hidden="true"><span>In The</span><span>Loop</span></div>
          </div>
          <form className="access-card" onSubmit={login}>
            <p className="eyebrow">INTERNAL OPERATIONS</p>
            <h1>{setupRequired ? '设置管理密码' : '进入运营工作台'}</h1>
            <p>{setupRequired ? '首次打开，请设置至少 8 位的管理密码。' : '输入团队管理密码。'}</p>
            {!backendConnected && <div className="preview-notice">后端服务没有响应。</div>}
            <label htmlFor="password">管理密码</label>
            <div className="password-row">
              <input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
              <button disabled={!password || loginBusy}>{loginBusy ? '验证中' : setupRequired ? '保存并进入' : '登录'}</button>
            </div>
            {loginError && <p className="error-text" role="alert">{loginError}</p>}
          </form>
        </section>
      ) : (
        <section className={`tool-workspace ${tool === 'website' ? 'website-workspace' : ''}`}>
          <header className="workspace-title">
            <div>
              <p className="eyebrow">IN THE LOOP / OPERATIONS</p>
              <h1>{tool === 'wechat' ? '公众号草稿' : '极客公园官网'}</h1>
            </div>
            <p>{tool === 'wechat' ? '飞书公开文档 → 微信公众号草稿箱' : '微信已发布文章或 Word → 极客公园官网'}</p>
          </header>

          {tool === 'wechat' ? (
            <WechatWorkspace
              settings={wechatSettings}
              appId={wechatAppId}
              secret={wechatSecret}
              accountName={wechatName}
              busy={wechatBusy}
              notice={wechatNotice}
              sourceUrl={feishuUrl}
              parsed={wechatParsed}
              onAppId={setWechatAppId}
              onSecret={setWechatSecret}
              onAccountName={setWechatName}
              onSourceUrl={setFeishuUrl}
              onSave={saveWechatSettings}
              onTest={testWechatConnection}
              onParse={parseFeishuDocument}
              onPublish={createWechatDraft}
              onReset={() => { setWechatParsed(null); setWechatNotice(''); }}
            />
          ) : (
            <WebsiteWorkspace
              status={websiteStatus}
              source={websiteSource}
              sourceUrl={websiteUrl}
              wordFile={wordFile}
              busy={websiteBusy}
              notice={websiteNotice}
              parsed={websiteParsed}
              selectedColumn={selectedColumn}
              publishResult={websitePublishResult}
              onConnect={connectWebsite}
              onSource={setWebsiteSource}
              onSourceUrl={setWebsiteUrl}
              onFile={acceptWordFile}
              onParse={parseWebsiteSource}
              onColumn={setSelectedColumn}
              onUpdate={updateWebsiteArticle}
              onPublish={publishWebsite}
              onReset={() => { setWebsiteParsed(null); setWebsiteNotice(''); setWebsitePublishResult(null); }}
            />
          )}
        </section>
      )}

      <footer><span>IN THE LOOP OPERATIONS / 2026</span><span>GEEKPARK INTERNAL</span></footer>
    </main>
  );
}

type WechatWorkspaceProps = {
  settings: WechatSettings | null;
  appId: string;
  secret: string;
  accountName: string;
  busy: BusyState;
  notice: string;
  sourceUrl: string;
  parsed: WechatParseResult | null;
  onAppId: (value: string) => void;
  onSecret: (value: string) => void;
  onAccountName: (value: string) => void;
  onSourceUrl: (value: string) => void;
  onSave: () => void;
  onTest: () => void;
  onParse: () => void;
  onPublish: () => void;
  onReset: () => void;
};

function WechatWorkspace(props: WechatWorkspaceProps) {
  const { settings, busy, notice, parsed } = props;
  if (parsed) {
    return (
      <div className="result-layout">
        <section className="preview-panel">
          <div className="preview-head">
            <button className="text-button" onClick={props.onReset}>返回导入</button>
            <span className="preview-label">微信预览</span>
          </div>
          <iframe className="document-preview wechat" title="微信全文预览" srcDoc={parsed.preview_html} sandbox="allow-same-origin" referrerPolicy="no-referrer" />
        </section>
        <aside className="publish-sidebar">
          <section className="meta-card">
            <div className="meta-title"><span className="success-pill">解析完成</span><small>{parsed.stats.image_count} 图 · {parsed.stats.video_count} 视频 · {parsed.stats.heading_count} 节</small></div>
            <h2>{parsed.article.title || '未识别标题'}</h2>
            <dl><div><dt>作者</dt><dd>{parsed.article.author || '未填写'}</dd></div><div><dt>编辑</dt><dd>{parsed.article.editor || '未填写'}</dd></div></dl>
            <p className="digest"><b>Why It Matters</b>{parsed.article.digest || '未填写'}</p>
            {parsed.warnings.length > 0 && <div className="warning-list">{parsed.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
          </section>
          <section className="action-panel">
            <div><strong>{settings?.account_name || 'In The Loop.具身现场'}</strong><small>{settings?.tested ? '连接已验证' : '连接未验证'}</small></div>
            <button className="primary-button compact" onClick={props.onPublish} disabled={busy !== '' || !settings?.tested}>{busy === 'draft' ? '正在创建草稿' : '保存到微信草稿箱'}</button>
          </section>
          {notice && <Notice text={notice} error={!notice.includes('成功')} />}
        </aside>
      </div>
    );
  }

  return (
    <div className="workspace-grid">
      <section className="control-panel connection-panel">
        <div className="section-heading"><span>01</span><div><h2>微信公众号连接</h2><p className={settings?.tested ? 'state-ok' : 'state-idle'}>{settings?.tested ? '已验证' : '未验证'}</p></div></div>
        <label>公众号名称<input value={props.accountName} onChange={(event) => props.onAccountName(event.target.value)} /></label>
        <label>AppID<input value={props.appId} onChange={(event) => props.onAppId(event.target.value)} autoComplete="off" /></label>
        <label>AppSecret<input type="password" value={props.secret} onChange={(event) => props.onSecret(event.target.value)} placeholder={settings?.has_secret ? '已保存，留空则不修改' : '输入 AppSecret'} autoComplete="new-password" /></label>
        <div className="button-row">
          <button className="secondary-button" onClick={props.onSave} disabled={!props.appId.trim() || (!settings?.has_secret && !props.secret) || busy !== ''}>{busy === 'saving' ? '保存中' : '保存配置'}</button>
          <button className="secondary-button" onClick={props.onTest} disabled={!settings?.has_secret || busy !== ''}>{busy === 'testing' ? '检测中' : '检测连接'}</button>
        </div>
      </section>
      <section className="control-panel source-panel">
        <div className="section-heading"><span>02</span><div><h2>导入飞书稿件</h2><p>公开文档链接</p></div></div>
        <label>飞书链接</label>
        <div className="stacked-input">
          <input value={props.sourceUrl} onChange={(event) => props.onSourceUrl(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && props.onParse()} placeholder="https://geek.feishu.cn/wiki/..." autoComplete="off" />
          <button className="primary-button" onClick={props.onParse} disabled={!props.sourceUrl.trim() || busy !== ''}>{busy === 'parsing' ? '正在读取正文和图片' : '解析并预览'}</button>
        </div>
        <div className="source-status"><span>输出</span><strong>微信公众号草稿箱</strong><small>不会直接群发</small></div>
      </section>
      {notice && <div className="grid-notice"><Notice text={notice} error={!notice.includes('成功') && !notice.includes('保存')} /></div>}
    </div>
  );
}

type WebsiteWorkspaceProps = {
  status: WebsiteStatus | null;
  source: 'url' | 'word';
  sourceUrl: string;
  wordFile: File | null;
  busy: BusyState;
  notice: string;
  parsed: WebsiteParseResult | null;
  selectedColumn: number;
  publishResult: PublishResult | null;
  onConnect: () => void;
  onSource: (source: 'url' | 'word') => void;
  onSourceUrl: (value: string) => void;
  onFile: (event: ChangeEvent<HTMLInputElement>) => void;
  onParse: () => void;
  onColumn: (column: number) => void;
  onUpdate: (patch: Partial<WebsiteArticle>) => void;
  onPublish: (mode: 'draft' | 'publish') => void;
  onReset: () => void;
};

function WebsiteWorkspace(props: WebsiteWorkspaceProps) {
  const { status, parsed, busy, notice } = props;
  if (parsed) {
    return (
      <div className="result-layout website-result">
        <section className="preview-panel">
          <div className="preview-head">
            <button className="text-button" onClick={props.onReset}>返回导入</button>
            <span className="preview-label">官网预览</span>
          </div>
          <iframe className="document-preview" title="官网文章预览" srcDoc={parsed.preview_html} sandbox="allow-same-origin" referrerPolicy="no-referrer" />
        </section>
        <aside className="publish-sidebar">
          <section className="editor-panel">
            <div className="meta-title"><span className="success-pill">解析完成</span><small>{parsed.article.cover_asset ? '已选取头图' : '无头图'}</small></div>
            <label>标题<input value={parsed.article.title} onChange={(event) => props.onUpdate({ title: event.target.value })} /></label>
            <label>摘要<textarea value={parsed.article.abstract} onChange={(event) => props.onUpdate({ abstract: event.target.value })} maxLength={500} /></label>
            <label>标签<input value={parsed.article.tags.join('，')} onChange={(event) => props.onUpdate({ tags: event.target.value.split(/[，,]/).map((tag) => tag.trim()).filter(Boolean).slice(0, 10) })} /></label>
            <label>栏目<select value={props.selectedColumn || ''} onChange={(event) => props.onColumn(Number(event.target.value))}><option value="">不指定栏目</option>{status?.columns.map((column) => <option value={column.id} key={column.id}>{column.title}</option>)}</select></label>
            {parsed.article.warnings.length > 0 && <div className="warning-list">{parsed.article.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
          </section>
          <section className="action-panel vertical">
            <div><strong>{status?.nickname || '极客公园官网'}</strong><small>{status?.connected ? '账号已连接' : '账号未连接'}</small></div>
            <div className="publish-buttons">
              <button className="secondary-button" onClick={() => props.onPublish('draft')} disabled={busy !== '' || !parsed.article.title.trim() || !status?.connected}>{busy === 'draft' ? '正在创建' : '保存草稿'}</button>
              <button className="primary-button compact" onClick={() => props.onPublish('publish')} disabled={busy !== '' || !parsed.article.title.trim() || !status?.connected}>{busy === 'publishing' ? '正在发布' : '直接发布'}</button>
            </div>
          </section>
          {notice && <Notice text={notice} error={!notice.includes('已') && !notice.includes('成功')} />}
          {props.publishResult?.admin_edit_url && <a className="result-link" href={props.publishResult.admin_edit_url} target="_blank" rel="noreferrer">打开官网后台文章</a>}
          {props.publishResult?.public_url && <a className="result-link" href={props.publishResult.public_url} target="_blank" rel="noreferrer">查看已发布文章</a>}
        </aside>
      </div>
    );
  }

  const canParse = props.source === 'url' ? Boolean(props.sourceUrl.trim()) : Boolean(props.wordFile);
  return (
    <div className="workspace-grid website-grid">
      <section className="control-panel connection-panel">
        <div className="section-heading"><span>01</span><div><h2>极客公园官网连接</h2><p className={status?.connected ? 'state-ok' : 'state-idle'}>{status?.connected ? '已连接' : '未连接'}</p></div></div>
        <dl className="connection-summary">
          <div><dt>服务器账号</dt><dd>{status?.fixed_credentials ? '已配置' : '未配置'}</dd></div>
          <div><dt>当前作者</dt><dd>{status?.nickname || '尚未连接'}</dd></div>
        </dl>
        <button className="secondary-button full" onClick={props.onConnect} disabled={!status?.fixed_credentials || busy !== ''}>{busy === 'connecting' ? '连接中' : status?.connected ? '重新检测连接' : '连接官网'}</button>
        {!status?.fixed_credentials && <p className="inline-help">请先在宝塔环境变量中填写官网账号和密码。</p>}
      </section>
      <section className="control-panel source-panel">
        <div className="section-heading"><span>02</span><div><h2>导入文章</h2><p>微信链接或 Word</p></div></div>
        <div className="segmented-control" role="tablist">
          <button className={props.source === 'url' ? 'active' : ''} onClick={() => props.onSource('url')}>微信文章链接</button>
          <button className={props.source === 'word' ? 'active' : ''} onClick={() => props.onSource('word')}>Word 文件</button>
        </div>
        {props.source === 'url' ? (
          <label>已发布微信文章<input value={props.sourceUrl} onChange={(event) => props.onSourceUrl(event.target.value)} placeholder="https://mp.weixin.qq.com/s/..." autoComplete="off" /></label>
        ) : (
          <div className="file-field">
            <input id="website-word-file" type="file" accept=".doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={props.onFile} />
            <label className="file-button" htmlFor="website-word-file">{props.wordFile ? '更换文件' : '选择 DOCX / DOC'}</label>
            <span>{props.wordFile?.name || '未选择文件'}</span>
          </div>
        )}
        <button className="primary-button full" onClick={props.onParse} disabled={!canParse || busy !== ''}>{busy === 'parsing' ? '正在读取正文和图片' : '解析并预览'}</button>
      </section>
      {notice && <div className="grid-notice"><Notice text={notice} error={!notice.includes('成功')} /></div>}
    </div>
  );
}

function Notice({ text, error }: { text: string; error: boolean }) {
  return <p className={`operation-notice ${error ? 'error' : 'success'}`} role={error ? 'alert' : 'status'}>{text}</p>;
}
