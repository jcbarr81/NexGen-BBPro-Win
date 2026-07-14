/**
 * Debounce a fast-changing value (e.g. a search input) before it feeds
 * something expensive like a React Query key. The raw value keeps driving
 * the controlled input so typing stays instant; consumers read the
 * debounced copy, which only settles after `delayMs` of quiet.
 */

import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(handle);
  }, [value, delayMs]);

  return debounced;
}
