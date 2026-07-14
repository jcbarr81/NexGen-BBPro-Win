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

import { useAuthStore } from "@/lib/auth-store";
import { fetchAuthedImage } from "@/lib/image-cache";
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
  // Re-fetch once the Firebase user is available (cold-load race — see PlayerAvatar).
  const uid = useAuthStore((s) => s.uid);

  useEffect(() => {
    let cancelled = false;
    setImgUrl(null);
    setLoaded(false);

    if (!teamId) return;

    // Fetched once per (league, team, version) via the shared image cache —
    // every mounted TeamLogo shares the same object URL, so a 500-row table
    // costs ~30 requests instead of 500. The URL is owned by the cache
    // (revoked on league switch / LRU eviction), not by this component.
    const key = `logo|${activeLeagueId ?? ""}|${teamId}|${version}`;
    void fetchAuthedImage(
      `/teams/${encodeURIComponent(teamId)}/logo`,
      key,
    ).then((url) => {
      if (cancelled) return;
      setImgUrl(url);
      setLoaded(true);
    });

    return () => {
      cancelled = true;
    };
  }, [teamId, token, version, activeLeagueId, uid]);

  if (imgUrl) {
    // Wrap + zoom-to-fill so the mascot fills the box everywhere the logo is
    // shown: the generated PNG has a baked-in margin around the artwork, which
    // otherwise makes logos look tiny in their container. ``className`` carries
    // the size/rounding; ``overflow-hidden`` clips the zoomed image.
    return (
      <div className={cn("overflow-hidden", className)}>
        <img
          src={imgUrl}
          alt={`${abbreviation} logo`}
          className="h-full w-full scale-[1.2] object-cover"
          loading="lazy"
        />
      </div>
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
