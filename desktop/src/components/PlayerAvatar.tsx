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

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setImgUrl(null);
    setLoaded(false);

    if (!playerId) return;

    const { apiBaseUrl, launchToken } = getBridge();
    const authToken = token ?? launchToken;
    const url = `${apiBaseUrl}/players/${encodeURIComponent(playerId)}/avatar`;

    fetch(url, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
    })
      .then(async (res) => {
        if (res.status === 204 || res.status === 404) return null;
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        if (!blob) {
          setLoaded(true);
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setImgUrl(objectUrl);
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [playerId, token, version]);

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
