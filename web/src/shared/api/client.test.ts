import { afterEach, describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { ApiError, createApiClient } from './client';

const schema = z.object({ value: z.string() });

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe('API boundary', () => {
  it('validates JSON and preserves explicit headers without leaking request data', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ value: 'ok' }));
    const client = createApiClient('/api/v1/', fetcher);
    const controller = new AbortController();
    const result = await client.request('/items', schema, {
      method: 'POST',
      headers: { 'X-Request-ID': 'safe-id' },
      body: JSON.stringify({ value: 'input' }),
      signal: controller.signal,
    });
    expect(result).toEqual({ value: 'ok' });
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/items',
      expect.objectContaining({ method: 'POST' }),
    );
    const options = fetcher.mock.calls[0]?.[1];
    expect(new Headers(options?.headers).get('Content-Type')).toBe('application/json');
    expect(new Headers(options?.headers).get('X-Request-ID')).toBe('safe-id');
  });

  it('handles empty DELETE responses and absolute endpoint URLs', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
    const result = await createApiClient('', fetcher).request(
      'https://example.test/item',
      z.undefined(),
      { method: 'DELETE' },
    );
    expect(result).toBeUndefined();
    expect(fetcher).toHaveBeenCalledWith('https://example.test/item', expect.any(Object));
  });

  it('exposes safe validation errors and correlation while omitting raw bodies', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: { code: 'validation_error', message: 'secret-input', request_id: 'request-123' },
        },
        { status: 422 },
      ),
    );
    const operation = createApiClient('/api/v1', fetcher).request('/items', schema);
    await expect(operation).rejects.toMatchObject({
      status: 422,
      code: 'validation_error',
      requestId: 'request-123',
      message: 'Sprawdź wprowadzone dane i spróbuj ponownie.',
    });
  });

  it('falls back to response headers for non-JSON HTTP errors', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('secret server detail', {
        status: 500,
        headers: { 'X-Request-ID': 'failure-1' },
      }),
    );
    await expect(
      createApiClient('/api/v1', fetcher).request('/items', schema),
    ).rejects.toMatchObject({ status: 500, code: 'http_error', requestId: 'failure-1' });
  });

  it('tolerates an error envelope without correlation or a valid response header', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ error: { code: 'not_found' } }, { status: 404 }));
    await expect(
      createApiClient('/api/v1', fetcher).request('/items', schema),
    ).rejects.toMatchObject({ status: 404, code: 'not_found', requestId: undefined });
  });

  it.each([Response.json({ value: 12 }), new Response('not-json')])(
    'rejects invalid success payloads',
    async (response) => {
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response);
      await expect(
        createApiClient('/api/v1', fetcher).request('/items', schema),
      ).rejects.toMatchObject({ code: 'invalid_response' });
    },
  );

  it('handles invalid success payloads with a correlation header', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(null, { headers: { 'X-Request-ID': 'invalid-1' } }));
    await expect(
      createApiClient('/api/v1', fetcher).request('/items', schema),
    ).rejects.toMatchObject({ requestId: 'invalid-1' });
  });

  it('uses safe messages for network failures and timeouts', async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new Error('secret credentials'));
    const client = createApiClient('/api/v1', fetcher);
    await expect(client.request('/items', schema)).rejects.toThrow(
      'Nie można połączyć się z serwerem.',
    );
    const timeout = new AbortController();
    timeout.abort();
    vi.spyOn(AbortSignal, 'timeout').mockReturnValue(timeout.signal);
    await expect(client.request('/items', schema)).rejects.toThrow(
      'Serwer nie odpowiedział na czas.',
    );
  });

  it('lets query cancellation propagate to its owner', async () => {
    const controller = new AbortController();
    controller.abort();
    const cancellation = new DOMException('Cancelled', 'AbortError');
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(cancellation);
    await expect(
      createApiClient('/api/v1', fetcher).request('/items', schema, { signal: controller.signal }),
    ).rejects.toBe(cancellation);
  });

  it('supports a hosted API URL and derives its health origin', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test/api/v1');
    vi.resetModules();
    const client = await import('./client');
    expect(client.apiBaseUrl).toBe('https://api.example.test/api/v1');
    expect(client.healthUrl).toBe('https://api.example.test/health/ready');
    expect(new ApiError('safe').name).toBe('ApiError');
  });
});
