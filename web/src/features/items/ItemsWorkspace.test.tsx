import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../shared/api/client';
import { ItemsWorkspace } from './ItemsWorkspace';
import { createItem, deleteItem, listItems, updateItem } from './api';
import type { Item } from './api';
import type * as ItemsApi from './api';

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof ItemsApi>()),
  listItems: vi.fn<typeof listItems>(),
  createItem: vi.fn<typeof createItem>(),
  updateItem: vi.fn<typeof updateItem>(),
  deleteItem: vi.fn<typeof deleteItem>(),
}));

const first: Item = {
  id: 'a662c7ab-2d08-429c-a33a-93c3178288a8',
  title: 'Pierwszy pomysł',
  description: 'Szczegóły pomysłu',
  created_at: '2026-11-17T12:00:00Z',
  updated_at: '2026-11-17T12:00:00Z',
};
let records: Item[];

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ItemsWorkspace />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  vi.clearAllMocks();
  records = [];
  vi.mocked(listItems).mockImplementation(async (offset) => ({
    items: records.slice(offset, offset + 20),
    limit: 20,
    offset,
    has_more: records.length > offset + 20,
  }));
  vi.mocked(createItem).mockImplementation(async (input) => {
    const item = { ...first, ...input };
    records.unshift(item);
    return item;
  });
  vi.mocked(updateItem).mockImplementation(async (id, input) => {
    const item = { ...first, ...input, id };
    records = records.map((record) => (record.id === id ? item : record));
    return item;
  });
  vi.mocked(deleteItem).mockImplementation(async (id) => {
    records = records.filter((record) => record.id !== id);
  });
});

describe('items workspace', () => {
  it('loads an empty collection and creates an item with a reset form', async () => {
    const user = setup();
    expect(await screen.findByText('Brak elementów.')).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Tytuł' }), 'Mój nowy pomysł');
    await user.type(screen.getByRole('textbox', { name: 'Opis (opcjonalnie)' }), '  Opis  ');
    await user.click(screen.getByRole('button', { name: 'Dodaj element' }));
    expect(await screen.findByRole('article', { name: 'Mój nowy pomysł' })).toHaveTextContent(
      'Opis',
    );
    expect(screen.getByRole('textbox', { name: 'Tytuł' })).toHaveValue('');
    expect(screen.getByRole('status')).toHaveTextContent('Element został dodany.');
    expect(createItem).toHaveBeenCalledWith(
      { title: 'Mój nowy pomysł', description: 'Opis' },
      expect.anything(),
    );
  });

  it('retains drafts and displays a safe correlated error when create fails', async () => {
    vi.mocked(createItem).mockRejectedValue(
      new ApiError('Sprawdź wprowadzone dane.', 422, 'validation_error', 'request-1'),
    );
    const user = setup();
    await screen.findByText('Brak elementów.');
    await user.type(screen.getByRole('textbox', { name: 'Tytuł' }), 'Draft');
    await user.click(screen.getByRole('button', { name: 'Dodaj element' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('request-1');
    expect(screen.getByRole('textbox', { name: 'Tytuł' })).toHaveValue('Draft');
  });

  it('shows a generic mutation error for unexpected failures without leaking it', async () => {
    vi.mocked(createItem).mockRejectedValue(new Error('private-driver-message'));
    const user = setup();
    await screen.findByText('Brak elementów.');
    await user.type(screen.getByRole('textbox', { name: 'Tytuł' }), 'Draft');
    await user.click(screen.getByRole('button', { name: 'Dodaj element' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się zapisać zmian.');
    expect(screen.queryByText('private-driver-message')).not.toBeInTheDocument();
  });

  it('updates an existing item and closes the edit dialog', async () => {
    records = [first];
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Edytuj Pierwszy pomysł' }));
    const dialog = screen.getByRole('dialog', { name: 'Edytuj element' });
    const title = within(dialog).getByRole('textbox', { name: 'Tytuł' });
    await user.clear(title);
    await user.type(title, 'Rozwinięty pomysł');
    await user.click(within(dialog).getByRole('button', { name: 'Zapisz zmiany' }));
    expect(await screen.findByRole('article', { name: 'Rozwinięty pomysł' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Zmiany zostały zapisane.');
  });

  it('cancels editing with the button, close control and native escape event', async () => {
    records = [{ ...first, description: null }];
    const user = setup();
    const edit = await screen.findByRole('button', { name: 'Edytuj Pierwszy pomysł' });
    await user.click(edit);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Anuluj' }));
    await user.click(edit);
    await user.click(screen.getByRole('button', { name: 'Zamknij okno' }));
    await user.click(edit);
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(updateItem).not.toHaveBeenCalled();
  });

  it('preserves a failed edit for retry', async () => {
    records = [first];
    vi.mocked(updateItem).mockRejectedValue(new ApiError('Zapis jest chwilowo niedostępny.'));
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Edytuj Pierwszy pomysł' }));
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Zapisz zmiany' }),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('Zapis jest chwilowo niedostępny.');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('confirms deletion and offers a cancellation path', async () => {
    records = [first];
    const user = setup();
    const remove = await screen.findByRole('button', { name: 'Usuń Pierwszy pomysł' });
    await user.click(remove);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Anuluj' }));
    expect(deleteItem).not.toHaveBeenCalled();
    await user.click(remove);
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(remove);
    await user.click(screen.getByRole('button', { name: 'Potwierdź usunięcie' }));
    expect(await screen.findByText('Brak elementów.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Element został usunięty.');
  });

  it('keeps the confirmation visible after a failed deletion', async () => {
    records = [first];
    vi.mocked(deleteItem).mockRejectedValue(new ApiError('Usunięcie jest chwilowo niedostępne.'));
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Usuń Pierwszy pomysł' }));
    await user.click(screen.getByRole('button', { name: 'Potwierdź usunięcie' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Usunięcie jest chwilowo niedostępne.',
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('retries a failed list request', async () => {
    vi.mocked(listItems).mockRejectedValueOnce(new ApiError('offline'));
    const user = setup();
    expect(await screen.findByRole('alert')).toHaveTextContent('Nie udało się pobrać elementów.');
    await user.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }));
    expect(await screen.findByText('Brak elementów.')).toBeInTheDocument();
  });

  it('shows loading status until the server responds', async () => {
    let resolve: ((value: Awaited<ReturnType<typeof listItems>>) => void) | undefined;
    vi.mocked(listItems).mockReturnValueOnce(
      new Promise((resolver) => {
        resolve = resolver;
      }),
    );
    setup();
    expect(screen.getByText('Wczytywanie elementów…')).toBeInTheDocument();
    resolve?.({ items: [], limit: 20, offset: 0, has_more: false });
    expect(await screen.findByText('Brak elementów.')).toBeInTheDocument();
  });

  it('paginates and returns to the prior page after deleting its last item', async () => {
    records = Array.from({ length: 21 }, (_, index) => ({
      ...first,
      id: String(index),
      title: `Pomysł ${String(index)}`,
    }));
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Następna strona' }));
    await waitFor(() => expect(screen.getByText('Strona 2')).toBeInTheDocument());
    await user.click(await screen.findByRole('button', { name: 'Poprzednia strona' }));
    expect(await screen.findByRole('article', { name: 'Pomysł 0' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Następna strona' }));
    await user.click(await screen.findByRole('button', { name: 'Usuń Pomysł 20' }));
    await user.click(screen.getByRole('button', { name: 'Potwierdź usunięcie' }));
    expect(await screen.findByRole('article', { name: 'Pomysł 0' })).toBeInTheDocument();
    expect(screen.getByText('Strona 1')).toBeInTheDocument();
  });
});
