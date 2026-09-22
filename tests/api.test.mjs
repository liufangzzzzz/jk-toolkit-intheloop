import assert from 'node:assert/strict';
import test from 'node:test';
import { api, validateWebsiteParseResult } from '../lib/api.ts';
import { forwardResponse, proxyHeaders } from '../lib/proxy.ts';

const good = () => ({ article: { title: '文章', abstract: '', content_html: '<p>正文</p>', cover_asset: '', source_type: 'docx', source_ref: 'test.docx', tags: [], warnings: [], image_issues: [] }, preview_html: '<html></html>' });

test('valid parse response is accepted, missing article/arrays are rejected before render', () => {
  validateWebsiteParseResult(good());
  for (const value of [{}, null, { article: {} }, { ...good(), article: { ...good().article, tags: null } }, { ...good(), article: { ...good().article, image_issues: [{}] } }]) {
    assert.throws(() => validateWebsiteParseResult(value), /解析结果不完整/);
  }
});
test('truncated successful HTTP response is an error, never an empty success', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => ({ ok: true, status: 200, json: async () => { throw new TypeError('terminated'); } }));
  await assert.rejects(api('/website-import/parse-file'), /结果传输不完整/);
});
test('non-JSON gateway error preserves HTTP status', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>error</html>', { status: 502 }));
  await assert.rejects(api('/website-import/parse-file'), /HTTP 502/);
});
test('backend validation message and disconnected requests remain actionable', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: { message: 'Word 文件为空或超过 60MB' } }, { status: 400 }));
  await assert.rejects(api('/website-import/parse-file'), /超过 60MB/);
  fetchMock.mock.mockImplementation(async () => { throw new TypeError('network error'); });
  await assert.rejects(api('/website-import/parse-file'), /连接中断/);
});
test('proxy removes obsolete framing/encoding but preserves auth and response type', async () => {
  const incoming = new Headers({ connection: 'keep-alive, x-hop', 'x-hop': 'remove', 'content-length': '3', cookie: 'session=test' });
  const outgoing = proxyHeaders(incoming);
  assert.equal(outgoing.get('x-hop'), null);
  assert.equal(outgoing.get('connection'), null);
  assert.equal(outgoing.get('cookie'), 'session=test');
  const result = await forwardResponse(new Response('already decoded', { headers: { 'content-encoding': 'gzip', 'content-length': '3', 'transfer-encoding': 'chunked', 'content-type': 'application/json', 'set-cookie': 'session=test; HttpOnly' } }));
  assert.equal(await result.text(), 'already decoded');
  for (const name of ['content-length', 'content-encoding', 'transfer-encoding']) assert.equal(result.headers.get(name), null);
  assert.equal(result.headers.get('set-cookie'), 'session=test; HttpOnly');
  assert.equal(result.headers.get('content-type'), 'application/json');
});
test('upstream stream failure is caught before constructing a success response', async () => {
  const response = new Response(new ReadableStream({ start(controller) { controller.error(new Error('truncated')); } }));
  await assert.rejects(forwardResponse(response), /truncated/);
});
test('empty 204 responses remain valid', async () => {
  const result = await forwardResponse(new Response(null, { status: 204 }));
  assert.equal(result.status, 204);
  assert.equal(await result.text(), '');
});
