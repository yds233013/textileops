"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, apiFetch } from "./api";

export interface Fetched<T> {
  data: T | null;
  error: ApiError | Error | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Minimal data hook. Deliberately not a caching library: an operations screen
 * should show what is true now, and every mutation reloads what it changed.
 */
export function useApi<T>(
  path: string | null,
  query?: Record<string, string | number | boolean | undefined | null>,
): Fetched<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [nonce, setNonce] = useState(0);
  const queryKey = JSON.stringify(query ?? {});

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    // A request is only abandoned when a *newer* one supersedes it. Tracking
    // mounted-ness as well would drop the second response of React's
    // development double-mount and leave the screen blank.
    let superseded = false;
    const controller = new AbortController();
    setLoading(true);

    apiFetch<T>(path, { query: query ?? undefined, signal: controller.signal })
      .then((result) => {
        if (superseded) return;
        setData(result);
        setError(null);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (superseded || controller.signal.aborted) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoading(false);
      });

    return () => {
      superseded = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, queryKey, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, error, loading, reload };
}

/** Run a mutation with pending/error state, for buttons and forms. */
export function useAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const run = useCallback(
    async (...args: TArgs): Promise<TResult | null> => {
      setPending(true);
      setError(null);
      try {
        return await action(...args);
      } catch (err: unknown) {
        setError(err instanceof Error ? err : new Error(String(err)));
        return null;
      } finally {
        setPending(false);
      }
    },
    [action],
  );

  return { run, pending, error, clearError: () => setError(null) };
}

/**
 * Read a query-string value once, on the client. Deliberately not
 * `useSearchParams`, which forces a Suspense boundary around every page that
 * uses it; these values only seed a filter's initial state.
 */
export function useInitialParam(name: string): string | null {
  const [value, setValue] = useState<string | null>(null);
  useEffect(() => {
    setValue(new URLSearchParams(window.location.search).get(name));
  }, [name]);
  return value;
}
