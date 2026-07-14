/**
 * Shared, deduplicated cache for auth-gated image endpoints (team logos,
 * player avatars).
 *
 * Previously every mounted TeamLogo/PlayerAvatar fired its own authenticated
 * fetch and revoked its object URL on unmount — a league-wide contracts table
 * meant hundreds of requests for ~30 unique logos, re-downloaded on every
 * navigation. Here each unique image is fetched once per session and every
 * component shares the same object URL.
 *
 * - Failures (e.g. the cold-load 401 before Firebase auth restores) are NOT
 *   cached — the next mount retries.
 * - Missing images (204/404) ARE cached as null so we don't re-poll them.
 * - Regeneration bumps `version`, which changes the cache key.
 * - LRU-capped so an avatar-heavy browse session can't grow unbounded.
 */

import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
import { firebaseEnabled, getIdToken } from "@/lib/firebase";

const cache = new Map<string, Promise<string | null>>();
const MAX_ENTRIES = 500;

/** Drop everything (league switch) — revokes all cached object URLs. */
export function clearImageCache(): void {
  for (const entry of cache.values()) {
    void entry.then((url) => {
      if (url) URL.revokeObjectURL(url);
    });
  }
  cache.clear();
}

function evictIfNeeded(): void {
  while (cache.size > MAX_ENTRIES) {
    const oldest = cache.entries().next().value;
    if (!oldest) return;
    const [key, entry] = oldest;
    cache.delete(key);
    void entry.then((url) => {
      if (url) URL.revokeObjectURL(url);
    });
  }
}

/**
 * Fetch an auth-gated image once and share the object URL. `cacheKey` must
 * encode everything that changes the response (id, version, league).
 * Returns null for missing images.
 */
export function fetchAuthedImage(
  path: string,
  cacheKey: string,
): Promise<string | null> {
  const existing = cache.get(cacheKey);
  if (existing) return existing;

  const promise = (async (): Promise<string | null> => {
    const { apiBaseUrl, launchToken } = getBridge();
    const { token, activeLeagueId } = useAuthStore.getState();
    const headers: Record<string, string> = {};
    const cloud = firebaseEnabled();
    const fbToken = cloud ? await getIdToken() : null;
    const bearer = fbToken ?? token ?? launchToken;
    if (bearer) headers.Authorization = `Bearer ${bearer}`;
    if (cloud && activeLeagueId) headers["X-League-Id"] = activeLeagueId;
    const res = await fetch(`${apiBaseUrl}${path}`, { headers });
    if (res.status === 204 || res.status === 404) return null;
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  })().catch(() => {
    // Don't cache failures — allow the retry that fires once auth restores.
    cache.delete(cacheKey);
    return null;
  });

  cache.set(cacheKey, promise);
  evictIfNeeded();
  return promise;
}
