/* eslint-disable react-hooks/exhaustive-deps */
import type { DependencyList } from "react";
import { useCallback, useEffect, useState } from "react";

function asyncErrorMessage(error: unknown): string {
  if (error instanceof TypeError && ["Failed to fetch", "Load failed"].includes(error.message)) {
    return "Não foi possível conectar ao servidor.";
  }
  return error instanceof Error ? error.message : "Erro inesperado";
}

export function useAsync<T>(
  loader: () => Promise<T>,
  deps: DependencyList = [],
  immediate = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (): Promise<T | null> => {
    setLoading(true);
    setError(null);
    try {
      const result = await loader();
      setData(result);
      return result;
    } catch (err) {
      setError(asyncErrorMessage(err));
      return null;
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
