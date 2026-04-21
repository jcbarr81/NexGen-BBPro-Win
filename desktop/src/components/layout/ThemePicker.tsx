/**
 * Theme + light/dark toggle. Lives in the header next to the help /
 * sign-out buttons. Uses the existing DropdownMenu primitive so the
 * hover/focus behaviour stays consistent with everything else.
 */

import { Check, Moon, Palette, Sun } from "lucide-react";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { THEMES, useThemeStore, type ThemeId } from "@/lib/theme";

export function ThemePicker() {
  const theme = useThemeStore((s) => s.theme);
  const mode = useThemeStore((s) => s.mode);
  const setTheme = useThemeStore((s) => s.setTheme);
  const toggleMode = useThemeStore((s) => s.toggleMode);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Theme">
          <Palette className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        {THEMES.map((t) => (
          <DropdownMenuItem
            key={t.id}
            onSelect={() => setTheme(t.id as ThemeId)}
          >
            <div className="flex w-full items-center justify-between gap-3">
              <div className="flex flex-col leading-tight">
                <span className="font-semibold">{t.label}</span>
                <span className="text-[10px] text-muted">{t.description}</span>
              </div>
              {t.id === theme && (
                <Check className="h-3 w-3 shrink-0 text-amber" aria-hidden />
              )}
            </div>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Color mode</DropdownMenuLabel>
        <DropdownMenuItem onSelect={toggleMode}>
          <div className="flex w-full items-center gap-2">
            {mode === "dark" ? (
              <Sun className="h-3.5 w-3.5" />
            ) : (
              <Moon className="h-3.5 w-3.5" />
            )}
            <span className="font-semibold">
              Switch to {mode === "dark" ? "light" : "dark"}
            </span>
          </div>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
