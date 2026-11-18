import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';

import { App } from './App';

afterEach(() => vi.unstubAllGlobals());

it('renders the starter without requiring a backend request', () => {
  const fetcher = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  expect(screen.getByRole('main')).toHaveTextContent('Aplikacja działa.');
  expect(fetcher).not.toHaveBeenCalled();
});

it('switches between both placeholders using the keyboard without requesting the API', async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetcher);
  render(<App />);

  const firstOption = screen.getByRole('button', { name: 'Opcja testowa 1' });
  const secondOption = screen.getByRole('button', { name: 'Opcja testowa 2' });
  expect(screen.getByRole('navigation', { name: 'Menu aplikacji' })).toBeVisible();
  expect(firstOption).toHaveAttribute('aria-pressed', 'true');
  expect(secondOption).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Opcja testowa 1');

  await user.tab();
  await user.tab();
  expect(secondOption).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(secondOption).toHaveAttribute('aria-pressed', 'true');
  expect(firstOption).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Opcja testowa 2');
  expect(screen.getByRole('main')).toHaveTextContent('To jest placeholder opcji testowej 2.');

  await user.tab({ shift: true });
  await user.keyboard(' ');
  expect(firstOption).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('main')).toHaveTextContent('To jest placeholder opcji testowej 1.');
  expect(fetcher).not.toHaveBeenCalled();
});
