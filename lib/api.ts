/** Reject unreadable responses instead of treating them as successful empty data. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: 'include' });
  } catch {
    throw new Error('连接中断，未能获取结果。请检查网络后重试。');
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(response.ok
      ? '结果传输不完整或格式异常，请重试；若持续出现，请联系部署人员检查代理服务。'
      : `请求失败（HTTP ${response.status}），请稍后重试。`);
  }
  if (!response.ok) {
    const detail = isRecord(payload) ? payload.detail : undefined;
    const message = typeof detail === 'string' ? detail : isRecord(detail) ? detail.message : undefined;
    throw new Error(typeof message === 'string' ? message : `请求失败（HTTP ${response.status}）`);
  }
  if (!isRecord(payload)) throw new Error('服务返回的数据格式异常，请重试。');
  return payload as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Validate everything the preview reads before switching out of the import screen. */
export function validateWebsiteParseResult(value: unknown): void {
  const invalid = () => { throw new Error('解析结果不完整，请重新解析。文件仍保留在待处理列表中。'); };
  if (!isRecord(value) || typeof value.preview_html !== 'string' || !isRecord(value.article)) return invalid();
  const article = value.article;
  for (const field of ['title', 'abstract', 'content_html', 'cover_asset', 'source_type', 'source_ref']) {
    if (typeof article[field] !== 'string') return invalid();
  }
  if (!String(article.title).trim() || !String(article.content_html).trim()) return invalid();
  for (const field of ['tags', 'warnings']) {
    if (!Array.isArray(article[field]) || !article[field].every((item) => typeof item === 'string')) return invalid();
  }
  if (!Array.isArray(article.image_issues) || !article.image_issues.every((issue) => (
    isRecord(issue) && typeof issue.index === 'number'
    && ['label', 'message', 'source_url', 'asset_url'].every((field) => typeof issue[field] === 'string')
  ))) return invalid();
}
