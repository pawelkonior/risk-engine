import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { createQueryClient } from './query-client';

export function App() {
  const [queryClient] = useState(createQueryClient);
  const [activeOption, setActiveOption] = useState(1);
  return (
    <QueryClientProvider client={queryClient}>
      <nav className="application-menu" aria-label="Menu aplikacji">
        {[1, 2].map((option) => (
          <button
            key={option}
            type="button"
            className="button"
            aria-pressed={activeOption === option}
            onClick={() => setActiveOption(option)}
          >
            Opcja testowa {option}
          </button>
        ))}
      </nav>
      <main>
        <h1>Opcja testowa {activeOption}</h1>
        <p>To jest placeholder opcji testowej {activeOption}.</p>
        <p>Aplikacja działa.</p>
      </main>
    </QueryClientProvider>
  );
}
