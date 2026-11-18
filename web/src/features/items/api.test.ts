import { afterEach, expect, it, vi } from 'vitest';

import { checkHealth, createItem, deleteItem, listItems, updateItem } from './api';

const item = {
  id: 'a662c7ab-2d08-429c-a33a-93c3178288a8',
  title: 'Pomysł',
  description: null,
  created_at: '2026-11-17T12:00:00Z',
  updated_at: '2026-11-17T12:00:00Z',
};

afterEach(() => vi.unstubAllGlobals());

it('uses the backend contract for list, create, update, delete and readiness', async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json({ items: [item], offset: 20, limit: 20, has_more: false }))
    .mockResolvedValueOnce(Response.json(item))
    .mockResolvedValueOnce(Response.json(item))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(Response.json({ status: 'ok', checks: { database: { status: 'ok' } } }));
  vi.stubGlobal('fetch', fetcher);
  const controller = new AbortController();
  expect((await listItems(20, controller.signal)).items).toHaveLength(1);
  await createItem({ title: 'Pomysł', description: null });
  await updateItem(item.id, { title: 'Pomysł', description: null });
  await deleteItem(item.id);
  await checkHealth();
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
    '/api/v1/items?limit=20&offset=20',
    '/api/v1/items',
    `/api/v1/items/${item.id}`,
    `/api/v1/items/${item.id}`,
    '/health/ready',
  ]);
});

it('passes readiness cancellation through its own endpoint', async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockImplementation(async () => Response.json({ status: 'ok' }));
  vi.stubGlobal('fetch', fetcher);
  await listItems(0).catch(() => undefined);
  await checkHealth(new AbortController().signal);
  expect(fetcher).toHaveBeenLastCalledWith('/health/ready', expect.any(Object));
});
