import { ArrowLeft, HelpCircle, LogOut, Undo2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Badge, Button } from "@/components/ui";
import { useAuthStore } from "@/lib/auth-store";
import { useThemeStore, type ThemeId } from "@/lib/theme";
import { popPrevious, useCanGoBack } from "@/lib/nav-history";
import { Breadcrumbs } from "./Breadcrumbs";
import { ThemePicker } from "./ThemePicker";
import dugoutHeader from "@/assets/Header_DugOut.png";
import grassHeader from "@/assets/Header_Grass.png";
import nightHeader from "@/assets/Header_NightGame.png";

interface HeaderProps {
  title?: string;
  subtitle?: string;
}

const HEADER_IMAGES: Record<ThemeId, string> = {
  dugout: dugoutHeader,
  grass: grassHeader,
  night: nightHeader,
};

export function Header({ title, subtitle }: HeaderProps) {
  const user = useAuthStore();
  const theme = useThemeStore((s) => s.theme);
  const navigate = useNavigate();
  const headerImage = HEADER_IMAGES[theme];

  const previous = user.previousSession;
  const canGoBack = useCanGoBack();
  function switchBack() {
    if (user.switchBackToPrevious()) {
      // After restoring the owner identity, drop back to the dashboard
      // (or My Team hub) so the team-scoped pages re-render with the
      // owner's team_id.
      navigate("/home");
    }
  }
  function goBack() {
    const prev = popPrevious();
    if (prev) navigate(prev);
  }

  return (
    <header
      className="sticky top-0 z-20 flex h-[140px] items-center justify-between gap-4 border-b border-border bg-canvas px-8 py-3 backdrop-blur"
      style={{
        // Header centerpiece — image is shown in full (contain) and
        // centered. ``auto 100%`` scales the image to the header height
        // while preserving its natural aspect, so nothing is cropped or
        // stretched. The gradient fades canvas color over the left and
        // right edges so the title (left) + user info (right) read
        // cleanly without overlapping the artwork.
        backgroundImage: `linear-gradient(to right, hsl(var(--canvas)) 0%, hsl(var(--canvas)) 18%, hsl(var(--canvas) / 0) 26%, hsl(var(--canvas) / 0) 74%, hsl(var(--canvas)) 82%, hsl(var(--canvas)) 100%), url(${headerImage})`,
        backgroundSize: "100% 100%, auto 100%",
        backgroundPosition: "center, center",
        backgroundRepeat: "no-repeat, no-repeat",
      }}
    >
      <div className="relative flex items-start gap-3">
        {/* In-app Back button — pops the nav-history stack so the user
            never lands on /login or /splash by accident. Hidden on the
            very first page since there's nothing to go back to. */}
        <Button
          variant="ghost"
          size="icon"
          onClick={goBack}
          disabled={!canGoBack}
          aria-label="Go back"
          title="Go back"
          className="mt-1"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <Breadcrumbs leafLabel={title} />
          <h1
            className="mt-0.5 font-display text-2xl font-bold leading-tight"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.55)" }}
          >
            {title ?? "NexGen-BBPro"}
          </h1>
        {subtitle && (
          <p
            className="text-sm text-muted"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.45)" }}
          >
            {subtitle}
          </p>
        )}
        </div>
      </div>

      <div className="relative flex items-center gap-3">
        {previous && (
          <Button
            size="sm"
            variant="outline"
            onClick={switchBack}
            title={`Restore ${previous.username} (${previous.role}) without re-typing the password`}
            className="border-amber/60 bg-amber/10 text-amber-text hover:bg-amber/20"
          >
            <Undo2 className="mr-1 h-3 w-3" />
            Back to {previous.username}
          </Button>
        )}
        <div className="text-right leading-tight">
          <div
            className="text-sm font-semibold"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.55)" }}
          >
            {user.username ?? "Guest"}
          </div>
          <div
            className="flex items-center justify-end gap-1.5 text-[11px] uppercase tracking-wider text-muted"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.45)" }}
          >
            <span>{user.role ?? "signed out"}</span>
            {previous && (
              <Badge tone="warning" className="text-[9px]">
                elevated
              </Badge>
            )}
          </div>
        </div>
        {user.token && (
          <>
            <ThemePicker />
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
