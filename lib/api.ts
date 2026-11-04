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
    const message = formatErrorDetail(detail);
    throw new Error(typeof message === 'string' ? message : `请求失败（HTTP ${response.status}）`);
  }
  if (!isRecord(payload)) throw new Error('服务返回的数据格式异常，请重试。');
  return payload as T;
}

function formatErrorDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail;
  if (isRecord(detail) && typeof detail.message === 'string') return detail.message;
  if (!Array.isArray(detail)) return undefined;
  const messages = detail.flatMap((item) => {
    if (!isRecord(item) || typeof item.msg !== 'string') return [];
    const loc = Array.isArray(item.loc) ? item.loc.filter((part) => typeof part === 'string' || typeof part === 'number') : [];
    const path = readableFieldPath(loc);
    return [`${path ? `${path}：` : ''}${translateValidationMessage(item.msg)}`];
  });
  return messages.length ? `提交内容未通过校验：${messages.join('；')}` : undefined;
}

function readableFieldPath(parts: (string | number)[]): string {
  const names: Record<string, string> = {
    body: '正文', title: '标题', abstract: '摘要', date: '日期', source_url: '原文链接',
    source_account: '来源', resources: '配套内容', label: '名称', label_en: '英文名称', url: '链接',
    article: '文章', request_id: '发布请求', account_id: '官网账号', content_html: '正文',
  };
  return parts.filter((part) => part !== 'body').map((part, index, all) => {
    if (typeof part === 'number') return `${part + 1}`;
    const name = names[part] || part;
    return typeof all[index + 1] === 'number' ? name : name;
  }).join('第').replace(/第(\d+)(?:第|$)/g, '第$1条');
}

function translateValidationMessage(message: string): string {
  if (/at least 1 character/i.test(message)) return '不能为空';
  if (/valid URL|URL scheme/i.test(message)) return '格式不正确，请填写完整的 http:// 或 https:// 链接';
  if (/at most (\d+) characters/i.test(message)) return message.replace(/String should have at most (\d+) characters/i, '不能超过 $1 个字符');
  if (/does not match pattern/i.test(message)) return '格式不正确';
  return message;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Validate everything the preview reads before switching out of the import screen. */
export function normalizeWebsiteParseResult(value: unknown): Record<string, unknown> {
  const invalid = (): never => { throw new Error('解析结果不完整，请重新解析。文件仍保留在待处理列表中。'); };
  if (!isRecord(value) || typeof value.preview_html !== 'string' || !isRecord(value.article)) return invalid();
  const article = value.article;
  for (const field of ['title', 'content_html']) if (typeof article[field] !== 'string') return invalid();
  if (!String(article.title).trim() || !String(article.content_html).trim()) return invalid();
  const strings = (input: unknown) => Array.isArray(input) ? input.filter((item): item is string => typeof item === 'string') : [];
  const issues = Array.isArray(article.image_issues) ? article.image_issues.filter(isRecord).map((issue, index) => ({
    index: typeof issue.index === 'number' ? issue.index : index + 1,
    label: typeof issue.label === 'string' ? issue.label : '',
    message: typeof issue.message === 'string' ? issue.message : '图片未能导入',
    source_url: typeof issue.source_url === 'string' ? issue.source_url : '',
    asset_url: typeof issue.asset_url === 'string' ? issue.asset_url : '',
  })) : [];
  return {
    ...value,
    article: {
      ...article,
      abstract: typeof article.abstract === 'string' ? article.abstract : '',
      cover_asset: typeof article.cover_asset === 'string' ? article.cover_asset : '',
      source_type: typeof article.source_type === 'string' ? article.source_type : 'docx',
      source_ref: typeof article.source_ref === 'string' ? article.source_ref : '',
      tags: strings(article.tags),
      warnings: strings(article.warnings),
      image_issues: issues,
    },
  };
}

export function validateWebsiteParseResult(value: unknown): void {
  normalizeWebsiteParseResult(value);
}
