import type { NextRequest } from 'next/server';
import { forwardResponse, proxyHeaders } from '../../../lib/proxy';

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const backend = (process.env.PUBLISHER_BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const target = new URL(`${backend}/api/${path.join('/')}`);
  target.search = request.nextUrl.search;

  const headers = proxyHeaders(request.headers);
  headers.delete('host');
  headers.set('accept-encoding', 'identity');

  try {
    const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
    // Forward uploads as a stream. Buffering the whole Word file here meant an
    // overseas upload had to finish one complete hop before backend parsing even
    // started, leaving the UI apparently spinning forever.
    const init: RequestInit & { duplex?: 'half' } = {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      signal: request.signal,
      redirect: 'manual',
    };
    if (hasBody) init.duplex = 'half';
    const response = await fetch(target, init);
    return await forwardResponse(response);
  } catch {
    return Response.json(
      { detail: { message: '后端连接或结果传输失败，请重试；若持续出现，请联系部署人员检查服务日志' } },
      { status: 503 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
