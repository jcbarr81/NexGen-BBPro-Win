// Refuse to build the web client without its Firebase sign-in config.
//
// The config lives in desktop/.env, which is not in git. A checkout without
// it (a fresh clone, or a deploy worktree whose untracked files were wiped)
// still builds -- into an app with no Google sign-in where every request
// fails "401 Missing bearer token". That shipped once (2026-11-06), so the
// build stops here instead.
import { loadEnv } from "vite";

const mode = process.argv[2] || "production";
const env = loadEnv(mode, process.cwd(), "VITE_");
const required = [
  "VITE_FIREBASE_API_KEY",
  "VITE_FIREBASE_AUTH_DOMAIN",
  "VITE_FIREBASE_PROJECT_ID",
  "VITE_FIREBASE_APP_ID",
];
const missing = required.filter((key) => !String(env[key] || "").trim());
if (missing.length) {
  console.error(
    `Build stopped: ${missing.join(", ")} not set (mode "${mode}"). ` +
      "Copy desktop/.env from a working checkout; without it the app has no sign-in."
  );
  process.exit(1);
}
console.log("Build env OK: Firebase sign-in config present.");
