import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";

/**
 * Button primitive, shadcn-compatible variant API.
 * - `primary`  — amber, brand CTAs (login, save, confirm)
 * - `secondary`— walnut surface with ink text (secondary actions)
 * - `ghost`    — transparent, hover raises (sidebar / toolbars)
 * - `outline`  — bordered, used on paper backgrounds
 * - `danger`   — destructive actions
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold transition " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber focus-visible:ring-offset-2 focus-visible:ring-offset-canvas " +
    "disabled:pointer-events-none disabled:opacity-60",
  {
    variants: {
      variant: {
        primary:
          "bg-amber text-espresso shadow-inset hover:bg-amber/90 active:translate-y-px",
        secondary:
          "bg-surfaceAlt text-ink border border-border hover:bg-elevated",
        ghost:
          "text-ink/80 hover:text-ink hover:bg-surfaceAlt",
        outline:
          "border border-border bg-transparent text-ink hover:bg-surfaceAlt",
        danger:
          "bg-danger text-cream hover:bg-danger/90 active:translate-y-px",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4",
        lg: "h-11 px-6 text-base",
        icon: "h-9 w-9 p-0",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
