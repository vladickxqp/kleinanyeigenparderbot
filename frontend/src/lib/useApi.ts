import { useEffect, useState } from "react";

interface State<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

// Generic one-shot data fetcher for read-only API calls.
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []): State<T> {
  const [state, setState] = useState<State<T>>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let alive = true;
    setState({ data: null, loading: true, error: null });
    fn()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((e: Error) =>
        alive && setState({ data: null, loading: false, error: e.message }),
      );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
