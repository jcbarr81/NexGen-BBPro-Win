import * as React from "react";

import { cn } from "@/lib/cn";

/** Text input with NexGen's warm palette + amber focus ring. */
export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, type = "text", ...props }, ref) => (
  <input
    ref={ref}
    type={type}
    className={cn(
      "flex h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 py-2 text-sm text-ink",
      "placeholder:text-subtle",
      "focus-visible:outline-none focus-visible:border-amber focus-visible:ring-2 focus-visible:ring-amber/40",
      "disabled:cursor-not-allowed disabled:opacity-60",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Label = React.forwardRef<
  HTMLLabelElement,
  React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn(
      "text-[11px] uppercase tracking-[0.12em] font-semibold text-muted",
      className,
    )}
    {...props}
  />
));
Label.displayName = "Label";
