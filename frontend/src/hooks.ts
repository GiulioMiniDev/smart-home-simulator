import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

export interface ResourceState<T> {
  data?: T;
  error?: ApiError;
  loading: boolean;
  reload: () => Promise<void>;
}

export function useResource<T>(path?: string): ResourceState<T> {
  const [state, setState] = useState<{ path?: string; data?: T; error?: ApiError; loading: boolean }>({
    path,
    loading: Boolean(path),
  });
  const generation = useRef(0);
  const request = useRef<AbortController | undefined>(undefined);
  const reload = useCallback(async () => {
    const currentGeneration = ++generation.current;
    request.current?.abort();
    if (!path) {
      request.current = undefined;
      setState({ path: undefined, loading: false });
      return;
    }
    const controller = new AbortController();
    request.current = controller;
    setState({ path, loading: true });
    try {
      const data = await api<T>(path, { signal: controller.signal });
      if (!controller.signal.aborted && currentGeneration === generation.current) {
        setState({ path, data, loading: false });
      }
    } catch (reason) {
      if (!controller.signal.aborted && currentGeneration === generation.current) {
        setState({ path, error: reason instanceof ApiError ? reason : new ApiError(String(reason), 0), loading: false });
      }
    }
  }, [path]);
  useEffect(() => {
    void reload();
    return () => {
      generation.current += 1;
      request.current?.abort();
    };
  }, [reload]);
  const current = state.path === path;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: Boolean(path) && (!current || state.loading),
    reload,
  };
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
