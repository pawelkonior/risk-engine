import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ItemForm } from './ItemForm';

describe('item form', () => {
  it('validates blank titles, trims input and allows an empty description', async () => {
    const user = userEvent.setup();
    const submit = vi
      .fn<(value: { title: string; description: string | null }) => Promise<void>>()
      .mockResolvedValue(undefined);
    render(<ItemForm busy={false} submitLabel="Dodaj element" onSubmit={submit} />);
    await user.type(screen.getByRole('textbox', { name: 'Tytuł' }), '   ');
    await user.click(screen.getByRole('button', { name: 'Dodaj element' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Wpisz tytuł elementu.');
    expect(submit).not.toHaveBeenCalled();
    await user.clear(screen.getByRole('textbox', { name: 'Tytuł' }));
    await user.type(screen.getByRole('textbox', { name: 'Tytuł' }), '  Mój pomysł  ');
    await user.click(screen.getByRole('button', { name: 'Dodaj element' }));
    expect(submit).toHaveBeenCalledWith({ title: 'Mój pomysł', description: null });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('preserves editing values and offers a cancel action', async () => {
    const user = userEvent.setup();
    const submit = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
    const cancel = vi.fn<() => void>();
    render(
      <ItemForm
        initial={{ title: 'Existing', description: 'Description' }}
        busy={false}
        submitLabel="Zapisz zmiany"
        onSubmit={submit}
        onCancel={cancel}
      />,
    );
    expect(screen.getByRole('textbox', { name: 'Tytuł' })).toHaveValue('Existing');
    await user.click(screen.getByRole('button', { name: 'Zapisz zmiany' }));
    expect(submit).toHaveBeenCalledWith({ title: 'Existing', description: 'Description' });
    await user.click(screen.getByRole('button', { name: 'Anuluj' }));
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('blocks oversized values even when a client bypasses input limits', async () => {
    const submit = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
    render(<ItemForm busy={false} submitLabel="Dodaj element" onSubmit={submit} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Tytuł' }), {
      target: { value: 'x'.repeat(201) },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Dodaj element' }).closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('200 znaków');
    fireEvent.change(screen.getByRole('textbox', { name: 'Tytuł' }), {
      target: { value: 'Title' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Opis (opcjonalnie)' }), {
      target: { value: 'x'.repeat(10_001) },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Dodaj element' }).closest('form')!);
    expect(submit).not.toHaveBeenCalled();
  });

  it('disables all mutable controls while saving', () => {
    render(
      <ItemForm
        busy
        submitLabel="Zapisz zmiany"
        onSubmit={vi.fn<() => Promise<void>>()}
        onCancel={vi.fn<() => void>()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Zapisywanie…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Anuluj' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Tytuł' })).toBeDisabled();
  });
});
