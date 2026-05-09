import { useEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { StatusRibbon } from "./StatusRibbon";
import { useHotkey } from "@/lib/use-hotkey";
import { FirstVisitTutorialAutoLauncher } from "@/components/help/FirstVisitTutorial";
import { recordNavigation } from "@/lib/nav-history";

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
  // Track in-app navigation so the Header's Back button can pop the
  // previous page. ``recordNavigation`` ignores auth/splash routes
  // so Back never strands the user on the login screen.
  useEffect(() => {
    recordNavigation(location.pathname);
  }, [location.pathname]);
  // Alt+/ opens Help from anywhere signed-in. Alt-slash is untaken by
  // Chrome/Electron and matches the "type / to search" convention elsewhere.
  useHotkey("alt+/", () => navigate("/help"));
  return (
    <div className="relative z-10 flex h-full min-h-0">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header title={title} subtitle={subtitle} />
        {teamAccentColor && (
          <div
            className="h-[3px] w-full"
            style={{ backgroundColor: teamAccentColor }}
            aria-hidden
          />
        )}
        <StatusRibbon />
        <main className="min-h-0 flex-1 overflow-auto px-8 py-6">
          {children}
        </main>
      </div>
      {/* Fires once per route-paired tutorial, on first visit, skippable,
          respects the global tutorial-enabled toggle. Mounted here so it
          works on every signed-in page without per-page wiring. */}
      <FirstVisitTutorialAutoLauncher />
    </div>
  );
}
