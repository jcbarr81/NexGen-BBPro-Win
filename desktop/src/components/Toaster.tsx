/**
 * Renders all active toasts from the toast-store. Mount once at the app
 * root — everywhere else just imports ``{ toast }`` and fires it.
 */

import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

import { cn } from "@/lib/cn";
import { useToasts, useToastActions, type ToastTone } from "@/lib/toast-store";

const ICON_MAP: Record<ToastTone, typeof AlertTriangle> = {
  error: AlertTriangle,
  success: CheckCircle2,
  info: Info,
};

const TONE_CLASSES: Record<ToastTone, string> = {
  error: "border-danger/40 bg-danger/10 text-danger",
  success: "border-success/40 bg-success/10 text-success",
  info: "border-amber/40 bg-amber/10 text-amber-text",
};

export function Toaster() {
  const entries = useToasts();
  const { dismiss } = useToastActions();

  if (entries.length === 0) return null;

  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2"
    >
      {entries.map((t) => {
        const Icon = ICON_MAP[t.tone];
        return (
          <div
            key={t.id}
            role="status"
            className={cn(
              "pointer-events-auto flex items-start gap-3 rounded-lg border bg-surface px-3 py-2 shadow-panel animate-fade-in",
              TONE_CLASSES[t.tone],
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-ink">{t.title}</div>
              {t.description && (
                <div className="mt-0.5 whitespace-pre-wrap break-words text-xs text-muted">
                  {t.description}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded-md p-1 text-muted transition hover:bg-surfaceAlt hover:text-ink"
              aria-label="Dismiss"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
