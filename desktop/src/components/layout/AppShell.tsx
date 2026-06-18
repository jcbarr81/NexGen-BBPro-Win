import { useEffect, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { StatusRibbon } from "./StatusRibbon";
import { useHotkey } from "@/lib/use-hotkey";
import { recordNavigation } from "@/lib/nav-history";
import { useLayoutEditStore } from "@/lib/layout-edit-store";

interface AppShellProps {
  title?: string;
  subtitle?: string;
  /**
   * When set, paints a 3-px stripe directly under the header using the
   * team's primary color. Used to visually tag "this page is about *this*
   * team" without repainting the whole chrome.
   */
  teamAccentColor?: string;
  children: ReactNode;
}

/**
 * Standard signed-in layout: sidebar nav + top header + scrollable content.
 */
export function AppShell({
  title,
  subtitle,
  teamAccentColor,
  children,
}: AppShellProps) {
  const navigate = useNavigate();
  const location = useLocation();
  // Mobile nav drawer (open from the header hamburger; the persistent rail at
  // lg+ ignores this).
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Track in-app navigation so the Header's Back button can pop the
  // previous page. ``recordNavigation`` ignores auth/splash routes
  // so Back never strands the user on the login screen. Also close the mobile
  // drawer on every route change.
  useEffect(() => {
    recordNavigation(location.pathname);
    setDrawerOpen(false);
    // Leave layout-edit mode whenever the route changes.
    useLayoutEditStore.getState().setEditing(false);
  }, [location.pathname]);
  // Alt+/ opens Help from anywhere signed-in. Alt-slash is untaken by
  // Chrome/Electron and matches the "type / to search" convention elsewhere.
  useHotkey("alt+/", () => navigate("/help"));
  return (
    <div className="relative z-10 flex h-full min-h-0">
      <Sidebar mobileOpen={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          title={title}
          subtitle={subtitle}
          onOpenMenu={() => setDrawerOpen(true)}
        />
        {teamAccentColor && (
          <div
            className="h-[3px] w-full"
            style={{ backgroundColor: teamAccentColor }}
            aria-hidden
          />
        )}
        <StatusRibbon />
        <main className="min-h-0 flex-1 overflow-auto px-3 py-4 sm:px-5 lg:px-8 lg:py-6">
          {children}
        </main>
      </div>
      {/* First-visit tutorial auto-launch removed: those tutorials are written
          for the old desktop UI and the modal overlay blocked sidebar clicks.
          Tutorials remain available on demand from Help → Tutorials. */}
    </div>
  );
}
