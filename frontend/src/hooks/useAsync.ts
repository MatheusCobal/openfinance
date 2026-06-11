/* eslint-disable react-hooks/exhaustive-deps */
import type { DependencyList } from "react";
import { useCallback, useEffect, useState } from "react";

export function useAsync<T>(
  loader: () => Promise<T>,
  deps: DependencyList = [],
  immediate = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await loader();
      setData(result);
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Erro inesperado";
      setError(message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, deps);

  useEffect(() => {
    if (!immediate) return;
    void run();
  }, [immediate, run]);

  return { data, loading, error, run, setData };
}
