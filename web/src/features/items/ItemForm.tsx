import { useId, useState } from 'react';
import type { FormEvent } from 'react';

import type { ItemInput } from './api';

interface ItemFormProps {
  initial?: ItemInput;
  busy: boolean;
  submitLabel: string;
  onSubmit: (value: ItemInput) => Promise<void>;
  onCancel?: () => void;
}

export function ItemForm({ initial, busy, submitLabel, onSubmit, onCancel }: ItemFormProps) {
  const id = useId();
  const [title, setTitle] = useState(initial?.title ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [validation, setValidation] = useState('');

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim()) {
      setValidation('Wpisz tytuł elementu.');
      return;
    }
    if (title.trim().length > 200 || description.length > 10_000) {
      setValidation('Tytuł może mieć do 200 znaków, a opis do 10 000 znaków.');
      return;
    }
    setValidation('');
    await onSubmit({ title: title.trim(), description: description.trim() || null });
  }

  return (
    <form
      className="item-form"
      onSubmit={(event) => {
        void handleSubmit(event);
      }}
      noValidate
    >
      <div className="field">
        <label htmlFor={`${id}-title`}>Tytuł</label>
        <input
          id={`${id}-title`}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Tytuł elementu"
          maxLength={200}
          required
          aria-invalid={Boolean(validation)}
          aria-describedby={validation ? `${id}-error` : undefined}
          disabled={busy}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-description`}>
          Opis <span>(opcjonalnie)</span>
        </label>
        <textarea
          id={`${id}-description`}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Opis elementu"
          maxLength={10_000}
          rows={4}
          disabled={busy}
        />
      </div>
      {validation && (
        <p className="field-error" role="alert" id={`${id}-error`}>
          {validation}
        </p>
      )}
      <div className="form-actions">
        {onCancel && (
          <button
            className="button button-secondary"
            type="button"
            onClick={onCancel}
            disabled={busy}
          >
            Anuluj
          </button>
        )}
        <button className="button button-primary" type="submit" disabled={busy}>
          {busy ? 'Zapisywanie…' : submitLabel}
        </button>
      </div>
    </form>
  );
}
