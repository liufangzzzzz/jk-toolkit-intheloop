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
    const body = request.method === 'GET' || request.method === 'HEAD'
      ? undefined
      : await request.arrayBuffer();

    const response = await fetch(target, {
      method: request.method,
      headers,
      body,
      redirect: 'manual',
    });
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
