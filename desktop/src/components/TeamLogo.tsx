/**
 * Renders a team's generated logo when one exists, falling back to a
 * colored-abbreviation square using the team's primary/secondary colors.
 *
 * The logo endpoint requires an auth bearer token, which ``<img src>``
 * can't carry, so we fetch the PNG as a blob and build an object URL.
 *
 * Pass ``version`` (a number that changes when you regenerate logos) to
 * invalidate the cached blob without a full unmount.
 */

import { useEffect, useState } from "react";

import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
import { firebaseEnabled, getIdToken } from "@/lib/firebase";
import { cn } from "@/lib/cn";

interface TeamLogoProps {
  teamId: string;
  abbreviation: string;
  primaryColor?: string;
  secondaryColor?: string;
  className?: string;
  /**
   * Bumps the fetch key so a regenerate triggers a refresh without the
   * parent having to unmount us. Queue the global "team-logos" query cache
   * into this number (e.g. `Date.now()` on generateLogos success).
   */
  version?: number;
}

export function TeamLogo({
  teamId,
  abbreviation,
  primaryColor,
  secondaryColor,
  className,
  version = 0,
}: TeamLogoProps) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const token = useAuthStore((s) => s.token);
  const activeLeagueId = useAuthStore((s) => s.activeLeagueId);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setImgUrl(null);
    setLoaded(false);

    if (!teamId) return;

    // The logo endpoint requires auth. In the cloud build that's the Firebase
    // ID token (+ X-League-Id so the server knows which league); locally it's
    // the legacy session/launch token. ``<img src>`` can't carry headers, so we
    // fetch the PNG as a blob with the right auth and build an object URL.
    (async () => {
      const { apiBaseUrl, launchToken } = getBridge();
      const url = `${apiBaseUrl}/teams/${encodeURIComponent(teamId)}/logo`;
      const headers: Record<string, string> = {};
      const cloud = firebaseEnabled();
      const fbToken = cloud ? await getIdToken() : null;
      const bearer = fbToken ?? token ?? launchToken;
      if (bearer) headers.Authorization = `Bearer ${bearer}`;
      if (cloud && activeLeagueId) headers["X-League-Id"] = activeLeagueId;
      try {
        const res = await fetch(url, { headers });
        if (cancelled) return;
        if (res.status === 204) {
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
  }, [teamId, token, version, activeLeagueId]);

  if (imgUrl) {
    return (
      <img
        src={imgUrl}
        alt={`${abbreviation} logo`}
        className={cn("object-contain", className)}
        loading="lazy"
      />
    );
  }

  // Fallback: colored square with abbreviation — matches the look the UI
  // had before logo generation was wired up.
  return (
    <div
      className={cn(
        "flex items-center justify-center rounded-lg border border-border font-display font-bold",
        loaded ? "" : "animate-pulse",
        className,
      )}
      style={{
        backgroundColor: primaryColor || "hsl(var(--surface-alt))",
        color: secondaryColor || "hsl(var(--ink))",
      }}
      aria-label={`${abbreviation} logo placeholder`}
    >
      {abbreviation}
    </div>
  );
}
