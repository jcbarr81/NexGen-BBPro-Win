/**
 * React-based replacement for ``window.confirm``. The native Electron
 * confirm leaves the BrowserWindow in a state where keystrokes no longer
 * reach inputs (see 6.10.10 Add-User regression after a delete). Use
 * this hook instead anywhere we'd reach for ``window.confirm``.
 *
 * Usage:
 *   const { confirm, dialog } = useConfirmDialog();
 *   ...
 *   if (await confirm({ title: "Delete?", description: "…", danger: true })) {
 *     mutate();
 *   }
 *   return <>{dialog}{...rest}</>;
 */

import { useCallback, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";

export interface ConfirmOptions {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Red button instead of amber — for destructive actions. */
  danger?: boolean;
}

interface PendingConfirm extends ConfirmOptions {
  resolve: (ok: boolean) => void;
}

export function useConfirmDialog() {
  const [pending, setPending] = useState<PendingConfirm | null>(null);

  const confirm = useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setPending({ ...options, resolve });
    });
  }, []);

  function close(result: boolean) {
    const p = pending;
    setPending(null);
    p?.resolve(result);
  }

  const dialog = (
    <Dialog
      open={pending !== null}
      onOpenChange={(next) => {
        if (!next) close(false);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              {pending?.danger && (
                <AlertTriangle className="h-4 w-4 text-danger" />
              )}
              {pending?.title ?? "Confirm"}
            </span>
          </DialogTitle>
          {pending?.description && (
            <DialogDescription>{pending.description}</DialogDescription>
          )}
        </DialogHeader>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => close(false)}>
            {pending?.cancelLabel ?? "Cancel"}
          </Button>
          <Button
            variant={pending?.danger ? "danger" : "primary"}
            onClick={() => close(true)}
          >
            {pending?.confirmLabel ?? "Continue"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );

  return { confirm, dialog };
}
