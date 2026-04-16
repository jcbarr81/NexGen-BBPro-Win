/**
 * Spawn and supervise the Python FastAPI sidecar.
 *
 * Dev mode: launches `python -m api --port 0 --print-handshake` from the
 * repo root so code changes under api/ are picked up on next restart.
 *
 * Packaged mode: launches the PyInstaller-built exe from
 * `process.resourcesPath/sidecar/NexGenBBProSidecar.exe`.
 *
 * In both cases we read a single JSON line from stdout --
 * `{ "port": <int>, "token": "<string>" }` -- before resolving the promise.
 */

import { ChildProcess, spawn } from "node:child_process";
import { app } from "electron";
import path from "node:path";

export interface SidecarHandshake {
  port: number;
  token: string;
}

export interface SidecarHandle extends SidecarHandshake {
  process: ChildProcess;
  baseUrl: string;
  wsUrl: string;
  kill: () => void;
}

const HANDSHAKE_TIMEOUT_MS = 30_000;

function resolveCommand(): { cmd: string; args: string[]; cwd: string } {
  const isPackaged = app.isPackaged;

  if (isPackaged) {
    const exe = path.join(
      process.resourcesPath,
      "sidecar",
      process.platform === "win32"
        ? "NexGenBBProSidecar.exe"
        : "NexGenBBProSidecar",
    );
    return {
      cmd: exe,
      args: ["--port", "0", "--print-handshake"],
      cwd: path.dirname(exe),
    };
  }

  // Dev: repo root is two levels up from desktop/dist-electron or desktop/electron.
  const repoRoot = path.resolve(__dirname, "..", "..");
  const pythonCmd =
    process.env.NEXGEN_PYTHON ||
    (process.platform === "win32" ? "python" : "python3");
  return {
    cmd: pythonCmd,
    args: ["-m", "api", "--port", "0", "--print-handshake"],
    cwd: repoRoot,
  };
}

export function spawnSidecar(): Promise<SidecarHandle> {
  const { cmd, args, cwd } = resolveCommand();

  const child = spawn(cmd, args, {
    cwd,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1",
    },
  });

  return new Promise<SidecarHandle>((resolve, reject) => {
    let resolved = false;
    let buffer = "";

    const timer = setTimeout(() => {
      if (resolved) return;
      child.kill();
      reject(new Error(`Sidecar handshake timed out after ${HANDSHAKE_TIMEOUT_MS}ms`));
    }, HANDSHAKE_TIMEOUT_MS);

    child.stdout?.setEncoding("utf-8");
    child.stdout?.on("data", (chunk: string) => {
      if (resolved) {
        process.stdout.write(`[sidecar] ${chunk}`);
        return;
      }
      buffer += chunk;
      const newlineIdx = buffer.indexOf("\n");
      if (newlineIdx === -1) return;

      const line = buffer.slice(0, newlineIdx).trim();
      buffer = buffer.slice(newlineIdx + 1);

      try {
        const handshake = JSON.parse(line) as SidecarHandshake;
        if (
          typeof handshake.port === "number" &&
          typeof handshake.token === "string"
        ) {
          resolved = true;
          clearTimeout(timer);
          const baseUrl = `http://127.0.0.1:${handshake.port}`;
          resolve({
            port: handshake.port,
            token: handshake.token,
            process: child,
            baseUrl,
            wsUrl: `ws://127.0.0.1:${handshake.port}`,
            kill: () => {
              try {
                child.kill();
              } catch {
                /* ignore */
              }
            },
          });
          return;
        }
      } catch {
        // Not a handshake line; stream remaining stdout to the parent for debugging.
        process.stdout.write(`[sidecar] ${line}\n`);
      }
    });

    child.stderr?.setEncoding("utf-8");
    child.stderr?.on("data", (chunk) => {
      process.stderr.write(`[sidecar] ${chunk}`);
    });

    child.on("error", (err) => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timer);
      reject(err);
    });

    child.on("exit", (code, signal) => {
      if (resolved) {
        console.warn(`[sidecar] exited code=${code} signal=${signal}`);
        return;
      }
      clearTimeout(timer);
      reject(new Error(`Sidecar exited before handshake (code=${code}, signal=${signal})`));
    });
  });
}

/** Poll /healthz until the sidecar is actually serving. */
export async function waitForHealth(
  baseUrl: string,
  { attempts = 40, delayMs = 250 }: { attempts?: number; delayMs?: number } = {},
): Promise<void> {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(`${baseUrl}/healthz`);
      if (res.ok) return;
    } catch {
      /* keep polling */
    }
    await new Promise((r) => setTimeout(r, delayMs));
  }
  throw new Error(`Sidecar /healthz never became ready at ${baseUrl}`);
}
