import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiError } from '../../shared/api/client';
import { Modal } from '../../shared/ui/Modal';
import { ItemForm } from './ItemForm';
import { createItem, deleteItem, listItems, pageSize, updateItem } from './api';
import type { Item, ItemInput } from './api';

const itemQueryKey = ['items'];

function MutationError({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <div className="error-box" role="alert">
      <p>
        {error instanceof ApiError
          ? error.message
          : 'Nie udało się zapisać zmian. Spróbuj ponownie.'}
      </p>
      {error instanceof ApiError && error.requestId && (
        <small>Identyfikator zgłoszenia: {error.requestId}</small>
      )}
    </div>
  );
}

function ItemCard({
  item,
  onEdit,
  onDelete,
}: {
  item: Item;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <article className="item-card" aria-label={item.title}>
      <div className="item-card-body">
        <div className="item-copy">
          <h3>{item.title}</h3>
          {item.description && <p>{item.description}</p>}
          <time dateTime={item.created_at}>
            {new Intl.DateTimeFormat('pl-PL', {
              day: 'numeric',
              month: 'long',
              year: 'numeric',
            }).format(new Date(item.created_at))}
          </time>
        </div>
      </div>
      <div className="item-actions">
        <button
          className="text-button"
          type="button"
          aria-label={`Edytuj ${item.title}`}
          onClick={onEdit}
        >
          Edytuj
        </button>
        <button
          className="text-button text-danger"
          type="button"
          aria-label={`Usuń ${item.title}`}
          onClick={onDelete}
        >
          Usuń
        </button>
      </div>
    </article>
  );
}

export function ItemsWorkspace() {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [formKey, setFormKey] = useState(0);
  const [editing, setEditing] = useState<Item | null>(null);
  const [deleting, setDeleting] = useState<Item | null>(null);
  const [notice, setNotice] = useState('');
  const items = useQuery({
    queryKey: [...itemQueryKey, offset],
    queryFn: ({ signal }) => listItems(offset, signal),
  });

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: itemQueryKey });
  }

  const creation = useMutation({ mutationFn: createItem });
  const update = useMutation({
    mutationFn: ({ id, input }: { id: string; input: ItemInput }) => updateItem(id, input),
  });
  const deletion = useMutation({ mutationFn: deleteItem });

  async function add(input: ItemInput) {
    try {
      await creation.mutateAsync(input);
      setOffset(0);
      setFormKey((value) => value + 1);
      setNotice('Element został dodany.');
      await refresh();
    } catch {
      // Mutation state supplies the public error. Preserve the user's input.
    }
  }

  async function save(input: ItemInput) {
    if (!editing) return;
    try {
      await update.mutateAsync({ id: editing.id, input });
      setEditing(null);
      setNotice('Zmiany zostały zapisane.');
      await refresh();
    } catch {
      // Keep the dialog and draft open for retry.
    }
  }

  async function remove() {
    if (!deleting) return;
    try {
      await deletion.mutateAsync(deleting.id);
      setDeleting(null);
      setNotice('Element został usunięty.');
      if (items.data?.items.length === 1 && offset > 0) setOffset(offset - pageSize);
      await refresh();
    } catch {
      // Keep the confirmation open and expose the mutation error.
    }
  }

  return (
    <div className="workspace">
      <aside className="composer-panel" aria-labelledby="new-item-heading">
        <h2 id="new-item-heading">Dodaj element</h2>
        <ItemForm
          key={formKey}
          busy={creation.isPending}
          submitLabel="Dodaj element"
          onSubmit={add}
        />
        <MutationError error={creation.error} />
      </aside>
      <section className="collection-panel" aria-labelledby="collection-heading">
        <div className="collection-heading">
          <div>
            <h2 id="collection-heading">Elementy</h2>
          </div>
          {items.data && (
            <span
              className="item-count"
              aria-label={`Elementy na stronie: ${String(items.data.items.length)}`}
            >
              {items.data.items.length.toString().padStart(2, '0')}
            </span>
          )}
        </div>
        <p className="sr-only" role="status" aria-live="polite">
          {notice}
        </p>
        {items.isPending ? (
          <div className="empty-state" role="status">
            <span className="loading-spinner" aria-hidden="true" />
            <h3>Wczytywanie elementów…</h3>
          </div>
        ) : items.isError ? (
          <div className="empty-state error-state" role="alert">
            <h3>Nie udało się pobrać elementów.</h3>
            <p>Sprawdź połączenie i spróbuj jeszcze raz.</p>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => {
                void items.refetch();
              }}
            >
              Spróbuj ponownie
            </button>
          </div>
        ) : items.data.items.length === 0 ? (
          <div className="empty-state">
            <p>Brak elementów.</p>
          </div>
        ) : (
          <div className="item-list">
            {items.data.items.map((item) => (
              <ItemCard
                key={item.id}
                item={item}
                onEdit={() => {
                  update.reset();
                  setEditing(item);
                }}
                onDelete={() => {
                  deletion.reset();
                  setDeleting(item);
                }}
              />
            ))}
          </div>
        )}
        <nav className="pagination" aria-label="Paginacja elementów">
          <button
            type="button"
            aria-label="Poprzednia strona"
            className="text-button"
            disabled={offset === 0 || items.isFetching}
            onClick={() => setOffset(Math.max(0, offset - pageSize))}
          >
            ← Poprzednia strona
          </button>
          <span>Strona {Math.floor(offset / pageSize) + 1}</span>
          <button
            type="button"
            aria-label="Następna strona"
            className="text-button"
            disabled={!items.data?.has_more || items.isFetching}
            onClick={() => setOffset(offset + pageSize)}
          >
            Następna strona →
          </button>
        </nav>
      </section>
      {editing && (
        <Modal
          title="Edytuj element"
          onClose={() => {
            if (!update.isPending) setEditing(null);
          }}
        >
          <ItemForm
            initial={editing}
            busy={update.isPending}
            submitLabel="Zapisz zmiany"
            onSubmit={save}
            onCancel={() => setEditing(null)}
          />
          <MutationError error={update.error} />
        </Modal>
      )}
      {deleting && (
        <Modal
          title="Usuń element"
          onClose={() => {
            if (!deletion.isPending) setDeleting(null);
          }}
        >
          <p className="modal-description">
            Czy na pewno chcesz usunąć „{deleting.title}”? Tej operacji nie można cofnąć.
          </p>
          <MutationError error={deletion.error} />
          <div className="form-actions">
            <button
              className="button button-secondary"
              type="button"
              onClick={() => setDeleting(null)}
              disabled={deletion.isPending}
            >
              Anuluj
            </button>
            <button
              className="button button-danger"
              type="button"
              disabled={deletion.isPending}
              onClick={() => {
                void remove();
              }}
            >
              {deletion.isPending ? 'Usuwanie…' : 'Potwierdź usunięcie'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
