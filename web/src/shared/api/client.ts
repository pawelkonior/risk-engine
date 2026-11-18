import { z } from 'zod';

const errorEnvelope = z.object({
  error: z.object({
    code: z.string(),
    request_id: z.string().nullish(),
  }),
});

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;

  constructor(message: string, status = 0, code = 'network_error', requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export function createApiClient(
  baseUrl: string,
  fetcher: typeof fetch = (...arguments_) => fetch(...arguments_),
) {
  const base = baseUrl.replace(/\/+$/, '');

  async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    options: RequestInit = {},
  ): Promise<T> {
    const timeout = AbortSignal.timeout(10_000);
    const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (options.body) headers.set('Content-Type', 'application/json');

    let response: Response;
    try {
      response = await fetcher(path.startsWith('/') ? `${base}${path}` : path, {
        ...options,
        headers,
        signal,
      });
    } catch (error) {
      if (options.signal?.aborted) throw error;
      throw new ApiError(
        timeout.aborted ? 'Serwer nie odpowiedział na czas.' : 'Nie można połączyć się z serwerem.',
      );
    }

    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      const parsed = errorEnvelope.safeParse(body);
      const code = parsed.success ? parsed.data.error.code : 'http_error';
      const requestId =
        (parsed.success ? parsed.data.error.request_id : undefined) ??
        response.headers.get('X-Request-ID') ??
        undefined;
      throw new ApiError(
        response.status === 422
          ? 'Sprawdź wprowadzone dane i spróbuj ponownie.'
          : 'Nie udało się wykonać operacji. Spróbuj ponownie.',
        response.status,
        code,
        requestId,
      );
    }

    const body: unknown =
      response.status === 204 ? undefined : await response.json().catch(() => null);
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new ApiError(
        'Serwer zwrócił nieprawidłową odpowiedź.',
        response.status,
        'invalid_response',
        response.headers.get('X-Request-ID') ?? undefined,
      );
    }
    return parsed.data;
  }

  return { request };
}

export const apiBaseUrl = import.meta.env['VITE_API_BASE_URL'] || '/api/v1';
export const api = createApiClient(apiBaseUrl);
export const healthApi = createApiClient('');
export const healthUrl = /^https?:\/\//.test(apiBaseUrl)
  ? new URL('/health/ready', apiBaseUrl).href
  : '/health/ready';
