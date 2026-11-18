import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { createQueryClient } from './query-client';

export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <header className="app-header">
        <details className="status-menu">
          <summary className="button">Menu</summary>
          <nav aria-label="Nawigacja główna">
            <a href="#app-status" tabIndex={0}>
              Stan aplikacji
            </a>
          </nav>
        </details>
      </header>
      <main id="app-status" tabIndex={-1}>
        <p>Aplikacja działa.</p>
      </main>
    </QueryClientProvider>
  );
}
