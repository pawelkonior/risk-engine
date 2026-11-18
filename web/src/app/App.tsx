import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { ItemsWorkspace } from '../features/items/ItemsWorkspace';
import { createQueryClient } from './query-client';

export function App() {
  const [queryClient] = useState(createQueryClient);
  const isItemsPage = window.location.pathname.replace(/\/$/, '') === '/items';

  return (
    <QueryClientProvider client={queryClient}>
      <header className="app-header">
        <nav className="app-nav" aria-label="Menu główne">
          <a href="/" aria-current={isItemsPage ? undefined : 'page'}>
            Strona główna
          </a>
          <a href="/items" aria-current={isItemsPage ? 'page' : undefined}>
            Elementy
          </a>
        </nav>
      </header>
      <main>{isItemsPage ? <ItemsWorkspace /> : <p>Aplikacja działa.</p>}</main>
    </QueryClientProvider>
  );
}
