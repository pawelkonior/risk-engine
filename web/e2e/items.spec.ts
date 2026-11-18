import { AxeBuilder } from '@axe-core/playwright';
import { randomUUID } from 'node:crypto';
import { expect, test as base } from '@playwright/test';
import { z } from 'zod';

const itemSchema = z.object({
  id: z.uuid(),
  title: z.string(),
  description: z.string().nullable(),
});
const healthSchema = z.object({ status: z.literal('ok') });
const test = base.extend<{ createdItems: string[] }>({
  createdItems: async ({ request }, provideFixture) => {
    const identifiers: string[] = [];
    try {
      await provideFixture(identifiers);
    } finally {
      for (const identifier of identifiers) {
        const response = await request.delete(`/api/v1/items/${identifier}`);
        expect(response.ok() || response.status() === 404).toBe(true);
      }
    }
  },
});

test('renders an accessible page at the configured viewport with the menu open', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page).toHaveTitle('Aplikacja');
  await expect(page.getByRole('main')).toHaveText('Aplikacja działa.');
  await page.getByText('Menu', { exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Nawigacja główna' })).toBeVisible();
  const viewport = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(viewport.content).toBeLessThanOrEqual(viewport.viewport);
  const accessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(
    accessibility.violations.map((violation) => ({
      id: violation.id,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
});

test('opens the menu and focuses the application status using the keyboard', async ({ page }) => {
  await page.goto('/');
  const menu = page.getByText('Menu', { exact: true });
  const statusLink = page.getByRole('link', { name: 'Stan aplikacji' });
  await expect(statusLink).toBeHidden();

  await page.keyboard.press('Tab');
  await expect(menu).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(statusLink).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(statusLink).toBeFocused();
  await page.keyboard.press('Enter');

  await expect(page).toHaveURL(/#app-status$/);
  await expect(page.getByRole('main')).toBeFocused();
});

test('connects the frontend proxy to the real API and persists an example resource', async ({
  page,
  request,
  createdItems,
}) => {
  const correlationId = `smoke-${randomUUID()}`;
  const health = await request.get('/health/ready', {
    headers: { 'X-Request-ID': correlationId },
  });
  expect(health.ok()).toBe(true);
  expect(healthSchema.parse(await health.json()).status).toBe('ok');
  expect(health.headers()['x-request-id']).toBe(correlationId);

  const title = `Test ${randomUUID()}`;
  const createdResponse = await request.post('/api/v1/items', {
    data: { title, description: 'Testowy element' },
  });
  expect(createdResponse.status()).toBe(201);
  const item = itemSchema.parse(await createdResponse.json());
  createdItems.push(item.id);
  const resource = `/api/v1/items/${item.id}`;
  const fetched = await request.get(resource);
  expect(fetched.ok()).toBe(true);
  expect(itemSchema.parse(await fetched.json())).toEqual(item);

  const updatedTitle = `${title} po zmianie`;
  const updatedResponse = await request.patch(resource, {
    data: { title: updatedTitle, description: null },
  });
  expect(updatedResponse.ok()).toBe(true);
  expect(itemSchema.parse(await updatedResponse.json())).toMatchObject({
    id: item.id,
    title: updatedTitle,
    description: null,
  });
  await page.goto('/');
  await page.reload();
  await expect(page.getByRole('main')).toHaveText('Aplikacja działa.');
  const persisted = await request.get(resource);
  expect(itemSchema.parse(await persisted.json()).title).toBe(updatedTitle);
  expect((await request.delete(resource)).status()).toBe(204);
  expect((await request.get(resource)).status()).toBe(404);
});

test('loads the page without depending on API availability', async ({ page }) => {
  let apiRequests = 0;
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route(/\/(?:api|health)\//, async (route) => {
    apiRequests += 1;
    await route.abort('failed');
  });
  await page.goto('/');
  await page.reload();
  await expect(page.getByRole('main')).toHaveText('Aplikacja działa.');
  expect(apiRequests).toBe(0);
  expect(errors).toEqual([]);
});
