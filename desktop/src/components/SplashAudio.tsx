/**
 * Background music for the splash + auth-flow screens, matching the
 * old PyQt splash (``ui/splash_screen._setup_music``): looped, seeks
 * to ~24s on first load to skip the intro, halved volume (auto-play
 * at 100% is hostile), persistent mute preference.
 *
 * Mounted unconditionally from App.tsx; ``activeOnRoutes`` controls
 * which paths actually play. Once the user enters the dashboard the
 * audio pauses, so the music stays scoped to the "starting the game"
 * experience.
 */

import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Volume2, VolumeX } from "lucide-react";

const STORAGE_KEY = "nexgen:splash-music-muted";
const AUDIO_SRC = "/splash.mp3";
const SEEK_TO_SECONDS = 24;
const DEFAULT_VOLUME = 0.5;

// Pages where the music should be audible — mirrors the PyQt splash
// window that played from launch through the login click.
const ACTIVE_PATHS: ReadonlyArray<RegExp> = [
  /^\/$/, // initial render before router resolves a path
  /^\/login(?:\?|$)/,
  /^\/select-league(?:\?|$)/,
  /^\/leagues\/new(?:\?|$)/,
];

function readMuted(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeMuted(muted: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, muted ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function SplashAudio() {
  const location = useLocation();
  const [muted, setMuted] = useState<boolean>(readMuted);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const seekedRef = useRef(false);

  const shouldPlay = ACTIVE_PATHS.some((re) => re.test(location.pathname));

  // Keep playback state in sync with route + mute toggle. Browsers can
  // still reject play() if autoplayPolicy isn't honored (e.g. unusual
  // build); the .catch keeps the rejection from surfacing in the
  // console as an unhandled promise rejection.
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    if (shouldPlay && !muted) {
      el.muted = false;
      el.volume = DEFAULT_VOLUME;
      void el.play().catch(() => undefined);
    } else {
      el.pause();
    }
  }, [shouldPlay, muted]);

  const handleLoaded = () => {
    const el = audioRef.current;
    if (!el || seekedRef.current) return;
    if (Number.isFinite(el.duration) && el.duration > SEEK_TO_SECONDS + 1) {
      try {
        el.currentTime = SEEK_TO_SECONDS;
      } catch {
        /* seeking can throw before metadata is fully ready */
      }
    }
    seekedRef.current = true;
  };

  const toggle = () => {
    setMuted((prev) => {
      const next = !prev;
      writeMuted(next);
      return next;
    });
  };

  return (
    <>
      <audio
        ref={audioRef}
        src={AUDIO_SRC}
        loop
        preload="auto"
        onLoadedMetadata={handleLoaded}
      />
      {shouldPlay && (
        <button
          type="button"
          onClick={toggle}
          aria-label={muted ? "Unmute splash music" : "Mute splash music"}
          title={muted ? "Unmute" : "Mute"}
          // Bottom-CENTER so it never collides with the sidebar version tag
          // (bottom-left) or the wizard's Back/Next buttons (bottom corners)
          // on /leagues/new, while staying clear of the centered auth cards.
          className="fixed bottom-2 left-1/2 z-50 flex h-7 w-7 -translate-x-1/2 items-center justify-center rounded-md border border-border bg-surfaceAlt/80 text-muted backdrop-blur transition hover:bg-surface hover:text-ink"
        >
          {muted ? (
            <VolumeX className="h-3.5 w-3.5" />
          ) : (
            <Volume2 className="h-3.5 w-3.5" />
          )}
        </button>
      )}
    </>
  );
}
