import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { App } from './App';

afterEach(() => {
  window.history.replaceState(null, '', '/');
  vi.unstubAllGlobals();
});

it('marks Start as current without requiring a backend request', () => {
  const fetcher = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  expect(screen.getByRole('link', { name: 'Start', current: 'page' })).toHaveAttribute('href', '/');
  expect(screen.getByRole('main')).toHaveTextContent('Aplikacja działa.');
  expect(fetcher).not.toHaveBeenCalled();
});

it('opens the existing items workspace from its URL', async () => {
  window.history.replaceState(null, '', '/items/');
  vi.stubGlobal(
    'fetch',
    vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ items: [], limit: 20, offset: 0, has_more: false })),
  );

  render(<App />);

  expect(screen.getByRole('link', { name: 'Elementy', current: 'page' })).toHaveAttribute(
    'href',
    '/items',
  );
  expect(await screen.findByText('Brak elementów.')).toBeVisible();
});
