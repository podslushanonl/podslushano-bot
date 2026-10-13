import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { QueryClient } from '@tanstack/react-query';

// Общий кэш данных: экран показывает сохранённое сразу и тихо обновляет в фоне.
// Кэш переживает перезапуск приложения — без интернета видно последнее загруженное.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 1000 * 60 * 60 * 24,
      retry: (n, e: any) => n < 2 && !(e?.status >= 400 && e?.status < 500),
      refetchOnWindowFocus: true,
    },
  },
});

export const persister = createAsyncStoragePersister({ storage: AsyncStorage, key: 'pn_cache_v1', throttleTime: 2000 });
