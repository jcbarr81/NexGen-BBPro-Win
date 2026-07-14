/**
 * Renders a player's generated avatar PNG when one exists, falling back to
 * the player's initials (or a generic User icon) in a colored square.
 *
 * Mirrors TeamLogo: the avatar endpoint is auth-gated, so <img src> can't
 * carry the bearer token — fetch as blob, build an object URL.
 */

import { useEffect, useState } from "react";
import { User } from "lucide-react";

import { useAuthStore } from "@/lib/auth-store";
import { fetchAuthedImage } from "@/lib/image-cache";
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
    setImgUrl(null);
    setLoaded(false);

    if (!playerId) return;

    // Fetched once per (league, player, version) via the shared image cache —
    // mirrors TeamLogo. ``version`` in the key (and URL) busts the cache after
    // a regenerate. The cache owns the object URLs (LRU-capped).
    const bust = version ? `?v=${version}` : "";
    const key = `avatar|${activeLeagueId ?? ""}|${playerId}|${version}`;
    void fetchAuthedImage(
      `/players/${encodeURIComponent(playerId)}/avatar${bust}`,
      key,
    ).then((url) => {
      if (cancelled) return;
      setImgUrl(url);
      setLoaded(true);
    });

    return () => {
      cancelled = true;
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
