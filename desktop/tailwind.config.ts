import type { Config } from "tailwindcss";

/**
 * Tokens ported from `ui/design_tokens.py` + `ui/theme_enhanced.py` so the
 * Electron UI reads as the same product as the PyQt build.
 *
 * Core palette is a warm, ballpark-leather aesthetic:
 *   espresso → deep_roast → mahogany → walnut (neutrals)
 *   amber (brand accent) · cream / parchment (paper + text on dark)
 *   red / navy / green (semantic highlights)
 *
 * Concrete color values live in CSS custom properties (see
 * `src/styles/tokens.css`) so they can swap between .dark and .light without a
 * re-render. The Tailwind colors below read those vars via `hsl(var(--token))`
 * so we get utility classes (`bg-surface`, `text-accent`, ...) that track the
 * active theme.
 */
const withVar = (name: string) => `hsl(var(${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
    },
    extend: {
      colors: {
        // Neutrals (surfaces + text)
        canvas: withVar("--canvas"),
        surface: withVar("--surface"),
        surfaceAlt: withVar("--surface-alt"),
        elevated: withVar("--elevated"),
        border: withVar("--border"),
        borderStrong: withVar("--border-strong"),
        ink: withVar("--ink"),
        muted: withVar("--muted"),
        subtle: withVar("--subtle"),

        // Brand
        amber: {
          DEFAULT: withVar("--amber"),
          dim: withVar("--amber-dim"),
          text: withVar("--amber-text"),
        },
        cream: withVar("--cream"),
        parchment: withVar("--parchment"),
        mahogany: withVar("--mahogany"),
        espresso: withVar("--espresso"),
        walnut: withVar("--walnut"),

        // Semantic
        success: withVar("--success"),
        warning: withVar("--warning"),
        danger: withVar("--danger"),
        info: withVar("--info"),

        // Baseball accents
        ballpark: {
          DEFAULT: withVar("--ballpark"),
          deep: withVar("--ballpark-deep"),
        },
        clay: withVar("--clay"),
        chalk: withVar("--chalk"),
        seam: withVar("--seam"),
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        display: ["\"Space Grotesk\"", "Inter", "sans-serif"],
        mono: ["\"JetBrains Mono\"", "ui-monospace", "Menlo", "monospace"],
      },
      fontSize: {
        // 12 / 13 / 14 / 16 / 18 / 22 / 28 / 36
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,253,240,0.04) inset, 0 10px 30px rgba(0,0,0,0.35)",
        inset: "inset 0 1px 0 rgba(255,253,240,0.06)",
        glow: "0 0 0 1px hsl(var(--amber) / 0.35), 0 8px 24px hsl(var(--amber) / 0.15)",
        scoreboard:
          "0 0 0 1px hsl(var(--scoreboard-glow) / 0.25), 0 0 18px hsl(var(--scoreboard-glow) / 0.35)",
      },
      borderRadius: {
        xl: "14px",
        "2xl": "18px",
      },
      backgroundImage: {
        grain:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='64' height='64' filter='url(%23n)' opacity='0.06'/%3E%3C/svg%3E\")",
        "sidebar-gradient":
          "linear-gradient(to right, hsl(var(--mahogany)), hsl(var(--espresso)))",
        // Thin diagonal pinstripes (yankees-era, subtle) — layer on top of
        // surface colors for a dugout/uniform feel on heroes + sidebar.
        pinstripes:
          "repeating-linear-gradient(90deg, hsl(var(--cream) / 0.06) 0 1px, transparent 1px 6px)",
        // Ballpark gradient — deep outfield grass into shadow.
        "field-gradient":
          "radial-gradient(circle at 50% 120%, hsl(var(--ballpark) / 0.7), hsl(var(--ballpark-deep) / 0.95) 65%, transparent 100%)",
        // Warning-track/clay arc for hero backdrops.
        "clay-gradient":
          "radial-gradient(circle at 50% 140%, hsl(var(--clay) / 0.55), transparent 60%)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 180ms ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
