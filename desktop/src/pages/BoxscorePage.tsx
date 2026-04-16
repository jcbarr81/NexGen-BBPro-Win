/**
 * Phase 4 port of ui/boxscore_window.py.
 *
 * Reads the rendered boxscore HTML from the sidecar and shows it in a
 * sandboxed iframe (srcdoc) so its inline styles don't leak into the
 * Electron shell. We pass the file path via a query string -- it can be
 * either an absolute path (matches what playoffs JSON stores) or relative
 * to the data/boxscores tree.
 */

import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, FileText, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";

export function BoxscorePage() {
  const [params] = useSearchParams();
  const path = params.get("path") ?? "";
  const navigate = useNavigate();

  const boxscore = useQuery({
    queryKey: ["boxscore", path],
    queryFn: () => api.boxscore(path),
    enabled: !!path,
  });

  return (
    <AppShell
      title="Box Score"
      subtitle={boxscore.data?.filename ?? path ?? "—"}
    >
      <div className="mb-4">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
      </div>

      {!path ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-warning">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">No boxscore path provided.</span>
          </CardContent>
        </Card>
      ) : boxscore.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading boxscore…</span>
          </CardContent>
        </Card>
      ) : boxscore.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(boxscore.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : boxscore.data ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="text-base">{boxscore.data.filename}</CardTitle>
              <div className="text-[11px] font-mono text-muted">
                {boxscore.data.path}
              </div>
            </div>
            <Badge tone="amber">
              <FileText className="h-3 w-3" /> HTML
            </Badge>
          </CardHeader>
          <CardContent className="p-0">
            <iframe
              title={boxscore.data.filename}
              srcDoc={boxscore.data.html}
              sandbox=""
              className="h-[70vh] w-full rounded-b-xl border-0 bg-white"
            />
          </CardContent>
        </Card>
      ) : null}
    </AppShell>
  );
}
