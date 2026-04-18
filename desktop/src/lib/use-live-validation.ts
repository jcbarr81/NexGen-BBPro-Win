/**
 * Fire a validation probe at the sidecar with a debounce, returning the
 * last result so pages can show inline errors/warnings while the user
 * edits — without spamming the server on every keystroke.
 */

import { useEffect, useRef, useState } from "react";

export interface LiveValidation {
  ok: boolean;
  errors: string[];
  warnings: string[];
  pending: boolean;
}

const IDLE: LiveValidation = { ok: true, errors: [], warnings: [], pending: false };

/**
 * @param probe  async () => {ok, errors, warnings}
 * @param deps   dependency values (e.g. [rows, vs]) — new probe fires
 *               when any change, after `delay` ms of silence
 * @param delay  debounce in ms; default 400
 */
export function useLiveValidation<T extends unknown[]>(
  probe: () => Promise<{ ok: boolean; errors: string[]; warnings: string[] }>,
  deps: T,
  delay = 400,
): LiveValidation {
  const [state, setState] = useState<LiveValidation>(IDLE);
  const timer = useRef<number | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const mine = ++seq.current;
      setState((prev) => ({ ...prev, pending: true }));
      probe()
        .then((res) => {
          if (mine !== seq.current) return;
          setState({
            ok: !!res.ok,
            errors: res.errors ?? [],
            warnings: res.warnings ?? [],
            pending: false,
          });
        })
        .catch(() => {
          if (mine !== seq.current) return;
          setState({ ok: true, errors: [], warnings: [], pending: false });
        });
    }, delay);
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
