import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";

export interface ResourceState<T> {
  data?: T;
  error?: ApiError;
  loading: boolean;
  reload: () => Promise<void>;
}

export function useResource<T>(path: string): ResourceState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError>();
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setData(await api<T>(path));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : new ApiError(String(reason), 0));
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, loading, reload };
}

export function useStoredState<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const stored = localStorage.getItem(key);
    return stored ? (JSON.parse(stored) as T) : initial;
  });
  const update = useCallback(
    (next: T) => {
      setValue(next);
      localStorage.setItem(key, JSON.stringify(next));
    },
    [key],
  );
  return [value, update];
}
