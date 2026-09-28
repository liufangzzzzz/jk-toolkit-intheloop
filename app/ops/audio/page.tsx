'use client';

import { ChangeEvent, useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../lib/api';
import './audio.css';

type SourceMode = 'link' | 'text' | 'file';
type Tier = 'transcript' | 'cleaned' | 'simple';
type Model = { id: string; name: string; tasks?: string[]; recommended?: boolean };
type Skills = { clean: string; simple: string; article: string };
type SourceStatus = { feishu_app_configured: boolean; feishu_user_configured: boolean; skills_configured: boolean; feishu_export_folder?: string };
type Project = {
  id?: string; revision: number; title: string; source_url: string; source_kind: string;
  transcript: string; cleaned: string; simple: string; article_title: string;
  article_summary: string; article_body: string; updated_at?: string;
};
type AudioWorkspaceState = {
  sourceMode: SourceMode; sourceUrl: string; pastedText: string; project: Project;
  model: string; articleModel: string; visibleTiers: Tier[]; correction: string; correctionModel: string;
};

const audioWorkspaceKey = 'itl-audio-workspace-v1';

const blankProject = (): Project => ({
  revision: 0, title: '', source_url: '', source_kind: 'text', transcript: '', cleaned: '',
  simple: '', article_title: '', article_summary: '', article_body: '',
});
const audioExtensions = new Set(['mp3', 'm4a', 'wav', 'aac', 'ogg', 'flac', 'mp4', 'mov']);

function isAudio(file: File | null) {
  return Boolean(file && audioExtensions.has((file.name.split('.').pop() || '').toLowerCase()));
}

export default function AudioStudio() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [sourceMode, setSourceMode] = useState<SourceMode>('link');
  const [sourceUrl, setSourceUrl] = useState('');
  const [pastedText, setPastedText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [project, setProject] = useState<Project>(blankProject);
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState('');
  const [articleModel, setArticleModel] = useState('');
  const [modelNotice, setModelNotice] = useState('');
  const [skills, setSkills] = useState<Skills>({ clean: '', simple: '', article: '' });
  const [sourceStatus, setSourceStatus] = useState<SourceStatus>({ feishu_app_configured: false, feishu_user_configured: false, skills_configured: false });
  const [rulesOpen, setRulesOpen] = useState(false);
  const [visibleTiers, setVisibleTiers] = useState<Tier[]>(['transcript', 'cleaned']);
  const [correction, setCorrection] = useState('');
  const [correctionModel, setCorrectionModel] = useState('');
  const [workspaceRestored, setWorkspaceRestored] = useState(false);
  const tierAreas = useRef<Partial<Record<Tier, HTMLTextAreaElement | null>>>({});
  const syncingScroll = useRef(false);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    const auth = await api<{ authenticated: boolean; setup_required?: boolean }>('/auth/me');
    setAuthenticated(auth.authenticated);
    if (!auth.authenticated) { window.location.replace('/ops'); return; }
    const [modelResult, skillResult, statusResult] = await Promise.all([
      api<{ models: Model[]; configured: boolean; notice?: string }>('/atlas/models'),
      api<Skills>('/audio-studio/skills'),
      api<SourceStatus>('/audio-studio/status'),
    ]);
    setModels(modelResult.models);
    setModelNotice(modelResult.notice || (!modelResult.configured ? '请先在服务器环境变量中配置模型接口。' : ''));
    setSkills(skillResult);
    setSourceStatus(statusResult);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function initialize() {
      try {
        await load();
      } catch (failure) {
        if (cancelled) return;
        setAuthenticated(false);
        setError(failure instanceof Error ? failure.message : '工作台连接失败');
        window.location.replace('/ops');
      }
    }
    void initialize();
    return () => { cancelled = true; };
  }, [load]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        const raw = window.sessionStorage.getItem(audioWorkspaceKey);
        if (raw) {
          const saved = JSON.parse(raw) as Partial<AudioWorkspaceState>;
          if (saved.sourceMode && ['link', 'text', 'file'].includes(saved.sourceMode)) setSourceMode(saved.sourceMode);
          if (typeof saved.sourceUrl === 'string') setSourceUrl(saved.sourceUrl);
          if (typeof saved.pastedText === 'string') setPastedText(saved.pastedText);
          if (saved.project && typeof saved.project === 'object') setProject({ ...blankProject(), ...saved.project });
          if (typeof saved.model === 'string') setModel(saved.model);
          if (typeof saved.articleModel === 'string') setArticleModel(saved.articleModel);
          if (Array.isArray(saved.visibleTiers)) {
            const tiers = saved.visibleTiers.filter((tier): tier is Tier => ['transcript', 'cleaned', 'simple'].includes(tier));
            if (tiers.length) setVisibleTiers(tiers.slice(0, 2));
          }
          if (typeof saved.correction === 'string') setCorrection(saved.correction);
          if (typeof saved.correctionModel === 'string') setCorrectionModel(saved.correctionModel);
        }
      } catch {
        window.sessionStorage.removeItem(audioWorkspaceKey);
      } finally {
        setWorkspaceRestored(true);
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!workspaceRestored) return;
    try {
      window.sessionStorage.setItem(audioWorkspaceKey, JSON.stringify({
        sourceMode, sourceUrl, pastedText, project, model, articleModel, visibleTiers, correction, correctionModel,
      } satisfies AudioWorkspaceState));
    } catch {
      // Keep the editor usable when a very large transcript exceeds browser storage.
    }
  }, [workspaceRestored, sourceMode, sourceUrl, pastedText, project, model, articleModel, visibleTiers, correction, correctionModel]);

  function update(patch: Partial<Project>) { setProject((current) => ({ ...current, ...patch })); }
  async function run(name: string, task: () => Promise<void>) {
    if (busy) return;
    setBusy(name); setNotice(''); setError('');
    try { await task(); } catch (failure) { setError(failure instanceof Error ? failure.message : '操作失败'); }
    finally { setBusy(''); }
  }

  async function deriveTexts(title: string, transcript: string) {
    if (!selectedProcessingModel) throw new Error('请先选择本次解析使用的模型。');
    return api<{ cleaned: string; simple: string }>('/audio-studio/process', {
      method: 'POST', body: JSON.stringify({ model: selectedProcessingModel, title, transcript }),
    });
  }

  async function importLink() {
    if (!sourceUrl.trim()) return;
    if (!selectedProcessingModel) { setError('请先选择模型；一次解析会直接生成原版、清洗版和简版。'); return; }
    await run('import', async () => {
      const result = await api<{ title: string; transcript: string; source_kind: string; needs_ai: boolean }>('/audio-studio/import-url', {
        method: 'POST', body: JSON.stringify({ url: sourceUrl.trim() }),
      });
      const title = result.title || project.title;
      const derived = await deriveTexts(title, result.transcript);
      update({ title, source_url: sourceUrl.trim(), source_kind: result.source_kind, transcript: result.transcript, ...derived });
      setVisibleTiers(['transcript', 'cleaned']);
      setNotice('原版、清洗版和简版已全部生成。可选择单独查看，或并列查看其中两份。');
    });
  }

  async function usePastedText() {
    if (!pastedText.trim()) return;
    if (!selectedProcessingModel) { setError('请先选择模型；一次解析会直接生成原版、清洗版和简版。'); return; }
    await run('import', async () => {
      const transcript = pastedText.trim();
      const derived = await deriveTexts(project.title, transcript);
      update({ source_kind: 'text', transcript, ...derived }); setVisibleTiers(['transcript', 'cleaned']);
      setNotice('原版、清洗版和简版已全部生成。可选择单独查看，或并列查看其中两份。');
    });
  }

  async function importFile() {
    if (!file) return;
    if (!selectedProcessingModel) { setError('请先选择模型；文件读取后会直接生成原版、清洗版和简版。'); return; }
    const needsAi = isAudio(file);
    if (needsAi && !selectedProcessingModel) { setError('这份音视频需要 AI 识别。请先明确选择模型，再点击开始识别。'); return; }
    await run(needsAi ? 'transcribe' : 'import', async () => {
      const form = new FormData(); form.set('file', file); if (needsAi) form.set('model', selectedProcessingModel);
      const result = await api<{ title: string; transcript: string; source_kind: string; needs_ai: boolean; notice?: string }>('/audio-studio/import-file', { method: 'POST', body: form });
      if (result.needs_ai) { setNotice(result.notice || '需要使用 AI 识别。'); return; }
      const title = result.title || project.title;
      const derived = await deriveTexts(title, result.transcript);
      update({ title, source_kind: result.source_kind, transcript: result.transcript, ...derived }); setVisibleTiers(['transcript', 'cleaned']);
      setNotice(needsAi ? `已使用 ${models.find((item) => item.id === selectedProcessingModel)?.name || selectedProcessingModel} 完成识别，并生成三个档位。` : '已读取文件，并生成原版、清洗版和简版。');
    });
  }

  async function processTranscript() {
    if (!selectedProcessingModel) { setError('请先选择本次使用的模型。'); return; }
    if (!project.transcript.trim()) { setError('请先导入或粘贴原始文字。'); return; }
    await run('process', async () => {
      const result = await api<{ cleaned: string; simple: string }>('/audio-studio/process', {
        method: 'POST', body: JSON.stringify({ model: selectedProcessingModel, title: project.title, transcript: project.transcript }),
      });
      update({ cleaned: result.cleaned, simple: result.simple }); setVisibleTiers(['transcript', 'cleaned']);
      setNotice('两份文本已生成。不确定片段已用颜色标出，请逐项核对。');
    });
  }

  async function generateArticle() {
    if (!selectedArticleModel) { setError('请先选择稿件生成模型。'); return; }
    const transcript = project.cleaned.trim();
    if (!transcript) { setError('请先生成并确认清洗版。稿件只基于清洗版生成。'); return; }
    await run('article', async () => {
      const result = await api<{ title: string; summary: string; body: string }>('/audio-studio/article', {
        method: 'POST', body: JSON.stringify({ model: selectedArticleModel, title: project.title, transcript, simple: project.simple }),
      });
      update({ article_title: result.title, article_summary: result.summary, article_body: result.body });
      setNotice('稿件草稿已基于清洗版生成，请编辑核对后再使用。');
    });
  }

  function toggleTier(tier: Tier) {
    setVisibleTiers((current) => {
      if (current.includes(tier)) return current.length === 1 ? current : current.filter((item) => item !== tier);
      return current.length < 2 ? [...current, tier] : [current[1], tier];
    });
  }

  function syncTierScroll(sourceTier: Tier, source: HTMLTextAreaElement) {
    if (visibleTiers.length !== 2 || syncingScroll.current) return;
    const otherTier = visibleTiers.find((tier) => tier !== sourceTier);
    const target = otherTier ? tierAreas.current[otherTier] : null;
    if (!target) return;
    const sourceRange = source.scrollHeight - source.clientHeight;
    const targetRange = target.scrollHeight - target.clientHeight;
    syncingScroll.current = true;
    target.scrollTop = sourceRange > 0 ? (source.scrollTop / sourceRange) * Math.max(0, targetRange) : 0;
    requestAnimationFrame(() => { syncingScroll.current = false; });
  }

  async function correctTexts() {
    if (!correction.trim()) { setError('请用一句话说明要纠正什么，例如“所有识别错的派森都是派资”。'); return; }
    if (!selectedCorrectionModel) { setError('请选择纠错使用的模型；这里可以选最便宜的模型。'); return; }
    if (!project.cleaned.trim()) { setError('请先生成清洗版。'); return; }
    await run('correct', async () => {
      const result = await api<{ cleaned: string; simple: string }>('/audio-studio/correct', {
        method: 'POST', body: JSON.stringify({ model: selectedCorrectionModel, instruction: correction.trim(), cleaned: project.cleaned, simple: project.simple }),
      });
      update(result); setNotice('AI 已按指令同步纠正清洗版和简版，原版保持不变。');
    });
  }

  async function saveSkills() {
    await run('skills', async () => {
      await api('/audio-studio/skills', { method: 'PUT', body: JSON.stringify(skills) });
      setSourceStatus((current) => ({ ...current, skills_configured: true }));
      setRulesOpen(false);
      setNotice('三套规则已保存，下一次生成会直接使用。');
    });
  }

  async function copy(value: string) {
    await navigator.clipboard.writeText(value); setNotice('已复制到剪贴板。');
  }

  async function exportFeishu(label: string, value: string) {
    if (!sourceStatus.feishu_user_configured) { setError('请先在 env 中配置飞书用户授权；导出文档必须以你的用户身份创建。'); return; }
    await run('feishu', async () => {
      const result = await api<{ url: string; folder_name?: string }>('/audio-studio/export-feishu', { method: 'POST', body: JSON.stringify({ title: `${project.title || '音频整理'} · ${label}`, content: value }) });
      window.open(result.url, '_blank', 'noopener,noreferrer');
      setNotice(`飞书文档已创建到“${result.folder_name || sourceStatus.feishu_export_folder || '沟通记录'}”。`);
    });
  }

  const tierMeta: Record<Tier, { label: string; value: string; placeholder: string }> = {
    transcript: { label: '原版', value: project.transcript, placeholder: '保留抓取到的时间轴、说话人和原始文字。' },
    cleaned: { label: '清洗版', value: project.cleaned, placeholder: '去除无意义重复，并标出不确定片段。' },
    simple: { label: '简版 · 时间轴', value: project.simple, placeholder: '沿原始时间轴讲清主要内容，保留报道所需的细节。' },
  };
  const processingModels = models.filter((item) => !item.tasks || item.tasks.includes('processing'));
  const articleModels = models
    .filter((item) => !item.tasks || item.tasks.includes('article'))
    .sort((left, right) => Number(Boolean(right.recommended)) - Number(Boolean(left.recommended)));
  const selectedProcessingModel = processingModels.some((item) => item.id === model) ? model : '';
  const selectedCorrectionModel = processingModels.some((item) => item.id === correctionModel) ? correctionModel : '';
  const selectedArticleModel = articleModels.some((item) => item.id === articleModel) ? articleModel : '';
  if (authenticated === null) return <main className="loading-screen"><span className="wordmark-mini">ITL</span><p>正在打开音频整理</p></main>;

  return <main className="app-shell audio-studio">
    <header className="topbar">
      <a className="brand" href="/ops"><span className="wordmark-mini">ITL</span><span><strong>In The Loop</strong><small>运营工作台</small></span></a>
      <nav className="tool-tabs" aria-label="运营工具"><a href="/ops?tool=wechat">公众号草稿</a><a href="/ops?tool=website">极客公园官网</a><a href="/ops/intheloop">InTheLoop 独立站</a><a className="active" href="/ops/audio">音频整理</a></nav>
      <div className="topbar-actions"><span className="mode-label">INTERNAL</span></div>
    </header>

    {!authenticated ? <section className="loading-screen"><span className="wordmark-mini">ITL</span><p>正在返回运营工作台</p></section> :
    <section className="tool-workspace audio-workspace">
      <header className="workspace-title"><div><p className="eyebrow">IN THE LOOP / AUDIO DESK</p><h1>音频整理</h1></div><p>优先读取现成 transcript。只有确实需要识别或生成时，才使用你明确选择的模型。</p></header>
      <div className="connection-cards" aria-label="必要配置">
        <div className={models.length ? 'ready' : 'pending'}><span>AI</span><strong>{models.length ? 'AI API 已配置' : 'AI API 未配置'}</strong><small>{models.length ? `${models.length} 个指定模型可选，每次由你决定` : '请在服务器 env 配置 Modelink API Key'}</small></div>
        <div className={sourceStatus.feishu_app_configured ? 'ready' : 'pending'}><span>FS</span><strong>{sourceStatus.feishu_app_configured ? sourceStatus.feishu_user_configured ? '飞书应用与用户身份已连接' : '飞书应用已连接' : '飞书应用未配置'}</strong><small>{sourceStatus.feishu_app_configured ? sourceStatus.feishu_user_configured ? `可读取妙记；文档导出到“${sourceStatus.feishu_export_folder || '沟通记录'}”` : '可读取机器人有权限的妙记；导出到你的空间还需用户授权' : '请在服务器 env 配置飞书应用'}</small></div>
        <div className={sourceStatus.skills_configured ? 'ready' : 'initial'}><span>SK</span><strong>{sourceStatus.skills_configured ? '生成规则已配置' : '正在使用初始规则'}</strong><small>清洗、简版与稿件规则可以随时修改</small><button onClick={() => setRulesOpen(true)}>{sourceStatus.skills_configured ? '修改' : '配置'} →</button></div>
      </div>
      {(notice || error || modelNotice) && <div className={`operation-notice audio-page-notice ${error ? 'error' : 'success'}`} role="status">{error || notice || modelNotice}</div>}

      <div className="audio-grid">
        <aside className="control-panel audio-source-panel">
          <div className="section-heading"><span>01</span><div><h2>放入素材</h2><p>链接、文字或文件</p></div></div>
          <div className="segmented-control three"><button className={sourceMode === 'link' ? 'active' : ''} onClick={() => setSourceMode('link')}>链接</button><button className={sourceMode === 'text' ? 'active' : ''} onClick={() => setSourceMode('text')}>粘贴文字</button><button className={sourceMode === 'file' ? 'active' : ''} onClick={() => setSourceMode('file')}>文件</button></div>
          {sourceMode === 'link' && <div className="source-box"><label>飞书妙记、Otter、小宇宙、YouTube、Bilibili 或其他公开链接<input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="https://…" /></label><button className="primary-button full" disabled={busy !== '' || !sourceUrl.trim() || !selectedProcessingModel} onClick={importLink}>{busy === 'import' ? '解析中…' : '解析为原版、清洗版与简版'}</button><p className="field-help">YouTube/Bilibili 先读取已有字幕，不下载视频；解析完成后直接得到三个档位。</p></div>}
          {sourceMode === 'text' && <div className="source-box"><label>Otter 导出文字或其他逐字稿<textarea value={pastedText} onChange={(e) => setPastedText(e.target.value)} placeholder="粘贴完整文字…" /></label><button className="primary-button full" disabled={!pastedText.trim() || busy !== '' || !selectedProcessingModel} onClick={usePastedText}>{busy === 'import' ? '解析中…' : '解析为原版、清洗版与简版'}</button></div>}
          {sourceMode === 'file' && <div className="source-box"><label className="file-pick">选择音频、视频、字幕、TXT、Markdown 或 Word<input type="file" accept="audio/*,video/mp4,video/quicktime,.txt,.md,.srt,.vtt,.doc,.docx" onChange={(e: ChangeEvent<HTMLInputElement>) => setFile(e.target.files?.[0] || null)} /><strong>{file ? file.name : '选择文件'}</strong></label>{isAudio(file) && <div className="ai-consent"><b>音视频需要先用 AI 识别</b><span>点击后依次完成识别、清洗和简版。</span></div>}<button className="primary-button full" disabled={!file || busy !== '' || !selectedProcessingModel} onClick={importFile}>{busy === 'transcribe' ? 'AI 识别中…' : busy === 'import' ? '解析中…' : '解析为三个档位'}</button></div>}
          <label>本次解析模型<select value={selectedProcessingModel} onChange={(e) => setModel(e.target.value)}><option value="">选择模型后开始</option>{processingModels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <button className="secondary-button full" disabled={!project.transcript || !selectedProcessingModel || busy !== ''} onClick={processTranscript}>{busy === 'process' ? '重新生成中…' : '重新生成清洗版与简版'}</button>
        </aside>

        <section className="audio-editor-panel">
          <div className="audio-title-row"><div><p className="editor-kicker">THREE TEXT LEVELS</p><strong>{project.title || '当前素材'}</strong></div></div>
          <nav className="output-tabs tier-selector" aria-label="选择显示的文字档位"><span>选择一个，或同时对照两个</span>{(['transcript', 'cleaned', 'simple'] as Tier[]).map((tier) => <button key={tier} aria-pressed={visibleTiers.includes(tier)} className={visibleTiers.includes(tier) ? 'active' : ''} onClick={() => toggleTier(tier)}>{tierMeta[tier].label}</button>)}</nav>

          <div className="output-pane compare-pane"><section className="ai-correction"><div><p className="editor-kicker">AI CORRECTION</p><strong>用一句话批量纠错</strong><small>同步检查清洗版和简版，原版始终保留。</small></div><label>纠错说明<input value={correction} onChange={(e) => setCorrection(e.target.value)} placeholder="例如：所有识别错的派森都是派资" /></label><label>纠错模型<select value={selectedCorrectionModel} onChange={(e) => setCorrectionModel(e.target.value)}><option value="">选择一个便宜模型</option>{processingModels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="secondary-button" disabled={!project.cleaned || !correction.trim() || !selectedCorrectionModel || busy !== ''} onClick={correctTexts}>{busy === 'correct' ? '检查中…' : '检查并替换'}</button></section><div className={`compare-grid tier-count-${visibleTiers.length}`}>{visibleTiers.map((tier) => <section key={tier}><div className="output-head"><h2>{tierMeta[tier].label}</h2></div><textarea ref={(node) => { tierAreas.current[tier] = node; }} value={tierMeta[tier].value} onScroll={(event) => syncTierScroll(tier, event.currentTarget)} onChange={(e) => update({ [tier]: e.target.value })} placeholder={tierMeta[tier].placeholder} /><div className="tier-actions"><button className="secondary-button" onClick={() => copy(tierMeta[tier].value)} disabled={!tierMeta[tier].value}>复制</button><button className="primary-button" onClick={() => exportFeishu(tierMeta[tier].label, tierMeta[tier].value)} disabled={!tierMeta[tier].value || !sourceStatus.feishu_user_configured || busy !== ''}>{busy === 'feishu' ? '导出中…' : '导出飞书文档 ↗'}</button></div></section>)}</div></div>
        </section>
      </div>

      <section className="article-workspace"><header><div><p className="eyebrow">03 / ARTICLE</p><h2>稿件单独生成</h2><p>只使用已确认的清洗版，按稿件规则再调用一次模型。推荐使用 Opus 4.6 或 Gemini 3.8 Flash。</p></div><div className="article-generate-controls"><label>稿件模型<select value={selectedArticleModel} onChange={(e) => setArticleModel(e.target.value)}><option value="">选择模型</option>{articleModels.map((item) => <option key={item.id} value={item.id}>{item.recommended ? `推荐 · ${item.name}` : item.name}</option>)}</select></label><button className="primary-button" disabled={!project.cleaned || !selectedArticleModel || busy !== ''} onClick={generateArticle}>{busy === 'article' ? '稿件生成中…' : '生成稿件'}</button></div></header>{project.article_body&&<div className="article-fields"><label>标题<input value={project.article_title} onChange={(e) => update({ article_title: e.target.value })} /></label><label>摘要<textarea value={project.article_summary} onChange={(e) => update({ article_summary: e.target.value })} /></label><label>正文<textarea className="article-body-field" value={project.article_body} onChange={(e) => update({ article_body: e.target.value })} /></label><div className="article-actions"><button className="secondary-button" onClick={() => copy([project.article_title, project.article_summary, project.article_body].filter(Boolean).join('\n\n'))}>复制稿件</button><button className="primary-button" disabled={!sourceStatus.feishu_user_configured || busy !== ''} onClick={() => exportFeishu('稿件', [project.article_title, project.article_summary, project.article_body].filter(Boolean).join('\n\n'))}>{busy === 'feishu' ? '导出中…' : '导出飞书文档 ↗'}</button></div></div>}</section>

      {rulesOpen && <div className="skill-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setRulesOpen(false); }}><section className="audio-skills-workspace" role="dialog" aria-modal="true" aria-labelledby="skill-title"><header><div><p className="eyebrow">AUDIO EDITORIAL SKILLS</p><h2 id="skill-title">生成规则</h2></div><button className="text-button" onClick={() => setRulesOpen(false)}>关闭</button></header><p>三套规则都从你提供的 Interview Transcript Editor 拆分而来，并按顺序衔接：清洗版是事实底稿；简版回看原稿并保留时间轴；稿件同时使用前两版。</p><div className="skill-rule-grid"><label>清洗版 · 中文可读版<textarea value={skills.clean} onChange={(e) => setSkills((s) => ({ ...s, clean: e.target.value }))} /></label><label>简版 · 个人使用版 / 时间轴<textarea value={skills.simple} onChange={(e) => setSkills((s) => ({ ...s, simple: e.target.value }))} /></label><label className="article-skill-rule">稿件版 · 极客公园访谈稿<textarea value={skills.article} onChange={(e) => setSkills((s) => ({ ...s, article: e.target.value }))} /></label></div><button className="primary-button full" onClick={saveSkills} disabled={busy !== ''}>{busy === 'skills' ? '保存中…' : '保存全部规则'}</button></section></div>}
    </section>}
  </main>;
}
