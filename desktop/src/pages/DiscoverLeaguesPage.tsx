import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Ticket } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui";
import { Brand } from "@/components/layout/Brand";
import { toast } from "@/lib/toast-store";

export function DiscoverLeaguesPage() {
  const navigate = useNavigate();
  const setActiveLeague = useAuthStore((s) => s.setActiveLeague);
  const [code, setCode] = useState("");
  const [redeeming, setRedeeming] = useState(false);
  const [requested, setRequested] = useState<Record<string, boolean>>({});

  const pub = useQuery({
    queryKey: ["public-leagues"],
    queryFn: () => api.listPublicLeagues(),
  });
  const leagues = pub.data?.leagues ?? [];

  async function redeem() {
    const c = code.trim().toUpperCase();
    if (!c) return;
    setRedeeming(true);
    try {
      const res = await api.redeemInvite(c);
      toast.success("Joined league", {
        description: res.team_id
          ? `You're in — team ${res.team_id}.`
          : "You're in — the commissioner will assign your team.",
      });
      setActiveLeague(res.league_id);
      navigate("/my-leagues", { replace: true });
    } catch (err) {
      toast.error("Couldn't redeem code", {
        description:
          err instanceof ApiError ? err.message.replace(/^\d+\s/, "") : "Invalid code.",
      });
    } finally {
      setRedeeming(false);
    }
  }

  async function request(leagueId: string) {
    try {
      await api.requestToJoin(leagueId);
      setRequested((r) => ({ ...r, [leagueId]: true }));
      toast.success("Request sent", {
        description: "The commissioner will review your request.",
      });
    } catch (err) {
      toast.error("Couldn't send request", {
        description:
          err instanceof ApiError ? err.message.replace(/^\d+\s/, "") : "Try again.",
      });
    }
  }

  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-3xl space-y-6 px-6 py-10">
        <div className="flex items-center justify-between">
          <Brand />
          <Button variant="ghost" size="sm" onClick={() => navigate("/my-leagues")}>
            <ArrowLeft className="h-4 w-4" /> Back
          </Button>
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Have an invite code?</CardTitle>
              <CardDescription>
                Enter a code from a commissioner to join their league instantly.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-end gap-2">
              <div className="flex-1 space-y-1.5">
                <Label htmlFor="code">Invite code</Label>
                <Input
                  id="code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.toUpperCase())}
                  placeholder="ABCD2345"
                  className="font-mono tracking-widest"
                />
              </div>
              <Button onClick={redeem} disabled={redeeming || !code.trim()}>
                {redeeming ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Ticket className="h-4 w-4" />
                )}
                Join
              </Button>
            </div>
          </CardContent>
        </Card>

        <div>
          <h2 className="mb-2 font-display text-lg">Public leagues</h2>
          {pub.isLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-amber" />
            </div>
          ) : leagues.length === 0 ? (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted">
                No public leagues are open right now.
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {leagues.map((l) => (
                <Card key={l.league_id}>
                  <CardContent className="flex items-center justify-between py-4">
                    <span className="font-semibold">{l.display_name}</span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={requested[l.league_id]}
                      onClick={() => request(l.league_id)}
                    >
                      {requested[l.league_id] ? "Requested" : "Request to join"}
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
