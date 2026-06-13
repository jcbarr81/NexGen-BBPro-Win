import { ArrowLeft, HelpCircle, LayoutGrid, LogOut, Menu, Undo2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Badge, Button } from "@/components/ui";
import { useAuthStore } from "@/lib/auth-store";
import { useIsDesktop } from "@/lib/use-media-query";
import { cloudLogout, isCloud } from "@/lib/cloud-auth";
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
  /** Opens the mobile nav drawer (the hamburger is hidden at lg+). */
  onOpenMenu?: () => void;
}

const HEADER_IMAGES: Record<ThemeId, string> = {
  dugout: dugoutHeader,
  grass: grassHeader,
  night: nightHeader,
};

export function Header({ title, subtitle, onOpenMenu }: HeaderProps) {
  const user = useAuthStore();
  const theme = useThemeStore((s) => s.theme);
  const navigate = useNavigate();
  const headerImage = HEADER_IMAGES[theme];
  const cloud = isCloud();
  // The banner artwork is a desktop decoration — on a phone the short, narrow
  // header makes the title overlap it. Show it only at lg+ (plain bg below).
  const isDesktop = useIsDesktop();

  async function handleSignOut() {
    if (cloud) {
      await cloudLogout();
      navigate("/login", { replace: true });
    } else {
      user.clear();
    }
  }

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
      className="sticky top-0 z-20 flex h-16 items-center justify-between gap-2 border-b border-border bg-canvas px-3 py-2 backdrop-blur sm:h-24 sm:gap-3 sm:px-5 lg:h-[140px] lg:gap-4 lg:px-8 lg:py-3"
      style={
        isDesktop
          ? {
              // Header centerpiece — image shown in full (contain) and centered.
              // The gradient fades canvas color over the left/right edges so the
              // title (left) + user info (right) read cleanly over the artwork.
              backgroundImage: `linear-gradient(to right, hsl(var(--canvas)) 0%, hsl(var(--canvas)) 18%, hsl(var(--canvas) / 0) 26%, hsl(var(--canvas) / 0) 74%, hsl(var(--canvas)) 82%, hsl(var(--canvas)) 100%), url(${headerImage})`,
              backgroundSize: "100% 100%, auto 100%",
              backgroundPosition: "center, center",
              backgroundRepeat: "no-repeat, no-repeat",
            }
          : undefined
      }
    >
      <div className="relative flex min-w-0 items-center gap-1.5 sm:items-start sm:gap-3">
        {/* Mobile hamburger — opens the nav drawer. Hidden at lg+ where the
            sidebar is always visible. */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenMenu}
          aria-label="Open menu"
          title="Menu"
          className="shrink-0 lg:hidden"
        >
          <Menu className="h-5 w-5" />
        </Button>
        {/* In-app Back button — pops the nav-history stack so the user
            never lands on /login or /splash by accident. */}
        <Button
          variant="ghost"
          size="icon"
          onClick={goBack}
          disabled={!canGoBack}
          aria-label="Go back"
          title="Go back"
          className="hidden shrink-0 sm:mt-1 sm:inline-flex"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0">
          <div className="hidden sm:block">
            <Breadcrumbs leafLabel={title} />
          </div>
          <h1
            className="truncate font-display text-lg font-bold leading-tight sm:mt-0.5 sm:text-xl lg:text-2xl"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.55)" }}
          >
            {title ?? "NexGen-BBPro"}
          </h1>
        {subtitle && (
          <p
            className="hidden truncate text-sm text-muted sm:block"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.45)" }}
          >
            {subtitle}
          </p>
        )}
        </div>
      </div>

      <div className="relative flex shrink-0 items-center gap-1 sm:gap-3">
        {previous && (
          <Button
            size="sm"
            variant="outline"
            onClick={switchBack}
            title={`Restore ${previous.username} (${previous.role}) without re-typing the password`}
            className="hidden border-amber/60 bg-amber/10 text-amber-text hover:bg-amber/20 sm:inline-flex"
          >
            <Undo2 className="mr-1 h-3 w-3" />
            Back to {previous.username}
          </Button>
        )}
        <div className="hidden text-right leading-tight sm:block">
          <div
            className="text-sm font-semibold"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.55)" }}
          >
            {(cloud ? user.handle : user.username) ?? "Guest"}
          </div>
          <div
            className="flex items-center justify-end gap-1.5 text-[11px] uppercase tracking-wider text-muted"
            style={{ textShadow: "0 1px 2px rgba(0,0,0,0.45)" }}
          >
            <span>{(cloud ? user.pkg : user.role) ?? "signed out"}</span>
            {previous && (
              <Badge tone="warning" className="text-[9px]">
                elevated
              </Badge>
            )}
          </div>
        </div>
        {(user.token || user.uid) && (
          <>
            {cloud && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate("/my-leagues")}
                title="Back to your leagues"
                className="px-2 sm:px-3"
              >
                <LayoutGrid className="h-3 w-3 sm:mr-1" />
                <span className="hidden sm:inline">My Leagues</span>
              </Button>
            )}
            <div className="hidden sm:block">
              <ThemePicker />
            </div>
            <Link to="/help" title="Help & Tutorials">
              <Button variant="ghost" size="icon" aria-label="Help">
                <HelpCircle className="h-4 w-4" />
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Sign out"
              onClick={handleSignOut}
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>
    </header>
  );
}
