/**
 * Renders a player's generated avatar PNG when one exists, falling back to
 * the player's initials (or a generic User icon) in a colored square.
 *
 * Mirrors TeamLogo: the avatar endpoint is auth-gated, so <img src> can't
 * carry the bearer token — fetch as blob, build an object URL.
 */

import { useEffect, useState } from "react";
import { User } from "lucide-react";

import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
import { firebaseEnabled, getIdToken } from "@/lib/firebase";
import { cn } from "@/lib/cn";

interface PlayerAvatarProps {
  playerId: string;
  initials?: string;
  className?: string;
  version?: number;
}

export function PlayerAvatar({
  playerId,
  initials,
  className,
  version = 0,
}: PlayerAvatarProps) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const token = useAuthStore((s) => s.token);
  const activeLeagueId = useAuthStore((s) => s.activeLeagueId);
  // Re-fetch once the Firebase user is available: on a cold load the avatar can
  // render before auth restores, getIdToken() returns null → 401, and ``token``
  // (legacy, always null in cloud) never changes to retrigger. ``uid`` does.
  const uid = useAuthStore((s) => s.uid);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setImgUrl(null);
    setLoaded(false);

    if (!playerId) return;

    // Cloud: send the Firebase ID token + X-League-Id (the endpoint is auth +
    // league-scoped); local: the legacy session/launch token. Mirrors TeamLogo.
    (async () => {
      const { apiBaseUrl, launchToken } = getBridge();
      // ``version`` busts the browser cache after a regenerate so the new image
      // shows instead of the stale one.
      const bust = version ? `?v=${version}` : "";
      const url = `${apiBaseUrl}/players/${encodeURIComponent(playerId)}/avatar${bust}`;
      const headers: Record<string, string> = {};
      const cloud = firebaseEnabled();
      const fbToken = cloud ? await getIdToken() : null;
      const bearer = fbToken ?? token ?? launchToken;
      if (bearer) headers.Authorization = `Bearer ${bearer}`;
      if (cloud && activeLeagueId) headers["X-League-Id"] = activeLeagueId;
      try {
        const res = await fetch(url, { headers });
        if (cancelled) return;
        if (res.status === 204 || res.status === 404) {
          setLoaded(true);
          return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImgUrl(objectUrl);
        setLoaded(true);
      } catch {
        if (!cancelled) setLoaded(true);
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [playerId, token, version, activeLeagueId, uid]);

  if (imgUrl) {
    return (
      <img
        src={imgUrl}
        alt={`${initials || playerId} avatar`}
        className={cn("object-cover", className)}
        loading="lazy"
      />
    );
  }

  return (
    <div
      className={cn(
        "flex items-center justify-center border border-border bg-surfaceAlt font-display font-bold text-amber-text",
        loaded ? "" : "animate-pulse",
        className,
      )}
      aria-label={`${initials || playerId} avatar placeholder`}
    >
      {initials || <User className="h-8 w-8" />}
    </div>
  );
}
