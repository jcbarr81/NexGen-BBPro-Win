import { useEffect, useState } from "react";
import { ExternalLink, PlayCircle } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

/**
 * The owners' how-to videos, played from the site's own /videos/ folder
 * (Firebase Hosting files, uploaded by scripts/videos_site.py, not part of
 * this build). The list matches /videos/index.html; lengths come from
 * /videos/durations.json when it loads.
 */
const VIDEOS: Array<{ name: string; title: string; about: string }> = [
  {
    name: "first-week",
    title: "Your first week as an owner",
    about:
      "The dashboard and its Spotlight, the commissioner's deadline, your roster, lineup, pitching staff and depth chart, then a week later: an injury, an open spot, and a call-up.",
  },
  {
    name: "trades",
    title: "Making trades",
    about:
      "Comparing and turning down an offer, then building your own with the acceptance meter.",
  },
  {
    name: "free-agency",
    title: "Free agency",
    about:
      "The bidding window, an offer that gets outbid on total, raising it, and the signing on his decision day.",
  },
  {
    name: "draft",
    title: "The amateur draft",
    about:
      "Your private draft board and when it picks for you, advancing to your turn, and making the pick.",
  },
];

const BASE = "/videos";

function length(seconds: number | undefined): string | null {
  if (!seconds) return null;
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * The one-minute promo for the sign-in page (8.13.0): a poster that becomes
 * the player when clicked. Hidden altogether if /videos/ is not there (a
 * local build, or before the videos are uploaded).
 */
export function PromoVideo() {
  const [playing, setPlaying] = useState(false);
  const [missing, setMissing] = useState(false);
  if (missing) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-semibold text-ink">NexGen-BBPro in a minute</span>
        <a
          href={`${BASE}/`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-1 text-xs text-amber hover:underline"
        >
          More videos <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      {playing ? (
        <video
          src={`${BASE}/promo.mp4`}
          poster={`${BASE}/promo.jpg`}
          controls
          autoPlay
          preload="metadata"
          className="aspect-video w-full rounded-md bg-black"
        />
      ) : (
        <button
          type="button"
          onClick={() => setPlaying(true)}
          className="group relative block w-full overflow-hidden rounded-md border border-border"
          aria-label="Play NexGen-BBPro in a minute"
        >
          <img
            src={`${BASE}/promo.jpg`}
            alt=""
            loading="lazy"
            onError={() => setMissing(true)}
            className="aspect-video w-full bg-black object-cover"
          />
          <span className="absolute inset-0 flex items-end justify-end bg-black/20 p-3 transition group-hover:bg-black/0">
            <PlayCircle className="h-10 w-10 text-amber drop-shadow" />
          </span>
        </button>
      )}
    </div>
  );
}

export function HelpVideos() {
  const [lengths, setLengths] = useState<Record<string, number>>({});
  const [playing, setPlaying] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`${BASE}/durations.json`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((d: unknown) => {
        if (live && d && typeof d === "object") {
          setLengths(d as Record<string, number>);
        }
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <PlayCircle className="h-4 w-4 text-amber" /> How-to videos
        </CardTitle>
        <CardDescription>
          Short videos for owners, filmed in a league made up for them.{" "}
          <a
            href={`${BASE}/`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-amber hover:underline"
          >
            All videos <ExternalLink className="h-3 w-3" />
          </a>
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {VIDEOS.map((v) => {
          const len = length(lengths[v.name]);
          return (
            <div
              key={v.name}
              className="rounded-lg border border-border bg-surfaceAlt/40 p-3"
            >
              {playing === v.name ? (
                <video
                  src={`${BASE}/${v.name}.mp4`}
                  poster={`${BASE}/${v.name}.jpg`}
                  controls
                  autoPlay
                  preload="metadata"
                  className="aspect-video w-full rounded-md bg-black"
                />
              ) : (
                <button
                  type="button"
                  onClick={() => setPlaying(v.name)}
                  className="group relative block w-full overflow-hidden rounded-md"
                  aria-label={`Play ${v.title}`}
                >
                  <img
                    src={`${BASE}/${v.name}.jpg`}
                    alt=""
                    loading="lazy"
                    className="aspect-video w-full bg-black object-cover"
                  />
                  {/* In the corner: the posters are title cards, so the
                      middle holds the video's name. */}
                  <span className="absolute inset-0 flex items-end justify-end bg-black/20 p-3 transition group-hover:bg-black/0">
                    <PlayCircle className="h-10 w-10 text-amber drop-shadow" />
                  </span>
                </button>
              )}
              <div className="mt-2 flex items-baseline justify-between gap-2">
                <div className="font-semibold text-ink">{v.title}</div>
                {len && <div className="text-xs text-muted">{len}</div>}
              </div>
              <p className="mt-1 text-xs leading-snug text-muted">{v.about}</p>
              <a
                href={`${BASE}/${v.name}-720p.mp4`}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-xs text-amber hover:underline"
              >
                Phone size
              </a>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
