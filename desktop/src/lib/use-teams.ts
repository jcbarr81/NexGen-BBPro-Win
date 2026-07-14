/**
 * Shared teams-list query.
 *
 * The teams list only changes on rare admin edits (team settings save
 * already invalidates ["teams"] explicitly) and the whole cache is wiped
 * on league switch (App.tsx LeagueCacheInvalidator), so it's safe to keep
 * it fresh for the session. Every page that needs team metadata should use
 * this hook instead of an ad-hoc useQuery so they all share one fetch.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useTeams(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    staleTime: Infinity,
    enabled: options?.enabled ?? true,
  });
}
