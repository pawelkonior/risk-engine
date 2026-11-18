import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { createQueryClient } from './query-client';

export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <main>
        <p>Aplikacja działa.</p>
      </main>
    </QueryClientProvider>
  );
}
