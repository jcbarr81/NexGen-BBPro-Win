import type { ReactNode } from "react";

import { Sidebar } from "./Sidebar";
import { Header } from "./Header";

interface AppShellProps {
  title?: string;
  subtitle?: string;
  children: ReactNode;
}

/**
 * Standard signed-in layout: sidebar nav + top header + scrollable content.
 */
export function AppShell({ title, subtitle, children }: AppShellProps) {
  return (
    <div className="relative z-10 flex h-full min-h-0">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header title={title} subtitle={subtitle} />
        <main className="min-h-0 flex-1 overflow-auto px-8 py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
