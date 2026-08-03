import { useCallback, useEffect, useRef, useState } from "react";

function asyncErrorMessage(error: unknown): string {
  if (error instanceof TypeError && ["Failed to fetch", "Load failed"].includes(error.message)) {
    return "Não foi possível conectar ao servidor.";
  }
  return error instanceof Error ? error.message : "Erro inesperado";
}

export function useAsync<T>(
  loader: () => Promise<T>,
  immediate = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);

  const run = useCallback(async (): Promise<T | null> => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const result = await loader();
      if (mountedRef.current && requestId === requestIdRef.current) {
        setData(result);
      }
      return result;
    } catch (err) {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setError(asyncErrorMessage(err));
      }
      return null;
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [loader]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!immediate) return;
    void run();
  }, [immediate, run]);

  return { data, loading, error, run, setData };
}
