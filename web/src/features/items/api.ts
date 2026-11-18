import { z } from 'zod';

import { api, healthApi, healthUrl } from '../../shared/api/client';

export const itemSchema = z.object({
  id: z.uuid(),
  title: z.string(),
  description: z.string().nullable(),
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
});

const pageSchema = z.object({
  items: z.array(itemSchema),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  has_more: z.boolean(),
});

const healthSchema = z.object({ status: z.literal('ok') });

export type Item = z.infer<typeof itemSchema>;
export interface ItemInput {
  title: string;
  description: string | null;
}
export const pageSize = 20;

export function listItems(offset: number, signal?: AbortSignal) {
  return api.request(`/items?limit=${String(pageSize)}&offset=${String(offset)}`, pageSchema, {
    signal: signal ?? null,
  });
}

export function createItem(input: ItemInput) {
  return api.request('/items', itemSchema, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function updateItem(id: string, input: ItemInput) {
  return api.request(`/items/${id}`, itemSchema, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export async function deleteItem(id: string) {
  await api.request(`/items/${id}`, z.undefined(), { method: 'DELETE' });
}

export function checkHealth(signal?: AbortSignal) {
  return healthApi.request(healthUrl, healthSchema, { signal: signal ?? null });
}
