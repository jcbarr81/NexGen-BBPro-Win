import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useHotkey } from "@/lib/use-hotkey";

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
        <main className="min-h-0 flex-1 overflow-auto px-8 py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
