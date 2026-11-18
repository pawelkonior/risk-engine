import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { ItemsWorkspace } from '../features/items/ItemsWorkspace';
import { createQueryClient } from './query-client';

export function App() {
  const [queryClient] = useState(createQueryClient);
  const isItemsPage = /^\/items\/?$/.test(window.location.pathname);

  return (
    <QueryClientProvider client={queryClient}>
      <header className="app-header">
        <p className="app-name">Risk Engine</p>
        <nav className="app-nav" aria-label="Menu główne">
          <a href="/" aria-current={isItemsPage ? undefined : 'page'}>
            Start
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
