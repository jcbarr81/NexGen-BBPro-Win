import { useParams } from "react-router-dom";
import { Construction } from "lucide-react";

import { AppShell } from "@/components/layout/AppShell";
import { Card, CardContent } from "@/components/ui";

/**
 * Placeholder for nav targets that haven't been ported yet. Phase 4 replaces
 * each of these routes with the real ported screen.
 */
export function ComingSoonPage({ label }: { label: string }) {
  const { "*": splat } = useParams();
  return (
    <AppShell title={label} subtitle={`Coming in Phase 4 · /${splat ?? label.toLowerCase()}`}>
      <Card className="flex min-h-[320px] items-center justify-center">
        <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
          <Construction className="h-10 w-10 text-amber" />
          <h2 className="font-display text-xl">{label} — not yet ported</h2>
          <p className="max-w-sm text-sm text-muted">
            The Phase 3 design system is in place. This screen will be wired up
            as part of the Phase 4 screen-by-screen port.
          </p>
        </CardContent>
      </Card>
    </AppShell>
  );
}
