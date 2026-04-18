import { HelpCircle, LogOut } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui";
import { useAuthStore } from "@/lib/auth-store";

interface HeaderProps {
  title?: string;
  subtitle?: string;
}

export function Header({ title, subtitle }: HeaderProps) {
  const user = useAuthStore();

  return (
    <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-border bg-canvas/80 px-8 py-4 backdrop-blur">
      <div>
        <h1 className="font-display text-2xl font-bold leading-tight">
          {title ?? "NexGen-BBPro"}
        </h1>
        {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-3">
        <div className="text-right leading-tight">
          <div className="text-sm font-semibold">
            {user.username ?? "Guest"}
          </div>
          <div className="text-[11px] uppercase tracking-wider text-muted">
            {user.role ?? "signed out"}
          </div>
        </div>
        {user.token && (
          <>
            <Link to="/help" title="Help & Tutorials">
              <Button variant="ghost" size="icon" aria-label="Help">
                <HelpCircle className="h-4 w-4" />
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Sign out"
              onClick={() => user.clear()}
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>
    </header>
  );
}
