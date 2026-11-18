import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { createQueryClient } from './query-client';

export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <header className="app-header">
        <nav className="app-nav" aria-label="Nawigacja główna">
          <a href="/" aria-current="page">
            Start
          </a>
        </nav>
      </header>
      <main>
        <p>Aplikacja działa.</p>
      </main>
    </QueryClientProvider>
  );
}
