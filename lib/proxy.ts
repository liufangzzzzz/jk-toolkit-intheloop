/** Headers describing a single connection must not cross a proxy boundary. */
export function proxyHeaders(source: Headers): Headers {
  const headers = new Headers(source);
  const connectionHeaders = (headers.get('connection') || '').split(',').map((name) => name.trim()).filter(Boolean);
  for (const name of [...connectionHeaders, 'connection', 'keep-alive', 'proxy-authenticate',
    'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length']) {
    headers.delete(name);
  }
  return headers;
}

export async function forwardResponse(response: Response): Promise<Response> {
  const headers = proxyHeaders(response.headers);
  // fetch decodes compressed response bodies. The upstream encoding/length no
  // longer describe these bytes; the serving HTTP layer must calculate its own.
  headers.delete('content-encoding');
  // Finish reading before sending success headers, so truncated upstream bodies
  // are caught by the route and become a regular JSON error rather than HTTP/2 errors.
  const body = [204, 205, 304].includes(response.status) ? null : await response.arrayBuffer();
  return new Response(body, { status: response.status, statusText: response.statusText, headers });
}
