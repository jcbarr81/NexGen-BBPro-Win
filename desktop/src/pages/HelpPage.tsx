/**
 * In-app help center. Serves as the entry point for:
 *  - The Electron UI manual (rendered from markdown).
 *  - The tutorial library (multi-step dialogs).
 *  - The legacy HTML manuals (game manual, finance system manual).
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { marked } from "marked";
import DOMPurify from "dompurify";
import {
  AlertTriangle,
  BookOpen,
  ExternalLink,
  FileText,
  GraduationCap,
  Loader2,
  PlayCircle,
  Search,
  X,
} from "lucide-react";

import { api } from "@/lib/api";
import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { TutorialDialog, type TutorialStep } from "@/components/help/TutorialDialog";
import { Input } from "@/components/ui";
import { useTutorialStore } from "@/lib/tutorial-store";

const MARKDOWN_SANITIZE = {
  ALLOWED_TAGS: [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "a", "ul", "ol", "li", "code", "pre",
    "b", "i", "em", "strong", "blockquote", "hr", "br",
    "table", "thead", "tbody", "tr", "th", "td", "span",
  ],
  ALLOWED_ATTR: ["href", "title", "id", "class", "target", "rel"],
};

const LEGACY_MANUAL_LABELS: Record<string, string> = {
  game: "Full game manual",
  finance: "Finance system manual",
  installer: "Installation manual",
};

export function HelpPage() {
  return (
    <AppShell
      title="Help & Tutorials"
      subtitle="Everything you need to know about the new UI"
    >
      <HelpBody />
    </AppShell>
  );
}

function HelpBody() {
  return (
    <Tabs defaultValue="manual">
      <TabsList>
        <TabsTrigger value="manual">
          <BookOpen className="mr-1 h-4 w-4" /> Manual
        </TabsTrigger>
        <TabsTrigger value="tutorials">
          <GraduationCap className="mr-1 h-4 w-4" /> Tutorials
        </TabsTrigger>
        <TabsTrigger value="legacy">
          <FileText className="mr-1 h-4 w-4" /> Legacy manuals
        </TabsTrigger>
      </TabsList>
      <TabsContent value="manual">
        <ManualTab />
      </TabsContent>
      <TabsContent value="tutorials">
        <TutorialsTab />
      </TabsContent>
      <TabsContent value="legacy">
        <LegacyManualsTab />
      </TabsContent>
    </Tabs>
  );
}

interface ManualSection {
  id: string;
  level: number;
  title: string;
  body: string; // markdown for this section (headings + following content)
}

/**
 * Parse the manual markdown into a flat list of sections keyed by the
 * first-level (##) headings. Each section keeps its own body text so we
 * can filter in/out of the rendered view based on a keyword search.
 */
function parseManualSections(markdown: string): ManualSection[] {
  const lines = markdown.split(/\r?\n/);
  const sections: ManualSection[] = [];
  let current: ManualSection | null = null;
  for (const line of lines) {
    const h2 = /^##\s+(.+)$/.exec(line);
    const h3 = /^###\s+(.+)$/.exec(line);
    if (h2) {
      if (current) sections.push(current);
      const title = h2[1].trim();
      current = {
        id: slugify(title),
        level: 2,
        title,
        body: `## ${title}\n`,
      };
      continue;
    }
    if (h3 && current) {
      current.body += `${line}\n`;
      continue;
    }
    if (current) current.body += `${line}\n`;
  }
  if (current) sections.push(current);
  return sections;
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function ManualTab() {
  const manual = useQuery({
    queryKey: ["help-manual"],
    queryFn: () => api.helpManual(),
  });
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);

  const sections = useMemo(() => {
    if (!manual.data?.content) return [];
    return parseManualSections(manual.data.content);
  }, [manual.data?.content]);

  const q = query.trim().toLowerCase();
  const filteredSections = useMemo(() => {
    if (!q) return sections;
    return sections.filter(
      (s) => s.title.toLowerCase().includes(q) || s.body.toLowerCase().includes(q),
    );
  }, [sections, q]);

  const renderedHtml = useMemo(() => {
    if (filteredSections.length === 0) return "";
    // Render each section on its own and wrap it in an anchor element carrying
    // the section id, so the Contents nav can scroll to it (marked doesn't add
    // these ids). The slug is alphanumeric + hyphens, so the wrapper is safe.
    return filteredSections
      .map((s) => {
        const raw = marked.parse(s.body, { async: false }) as string;
        const safe = DOMPurify.sanitize(raw, MARKDOWN_SANITIZE);
        return `<section id="manual-section-${s.id}" style="scroll-margin-top:1rem">${safe}</section>`;
      })
      .join("\n");
  }, [filteredSections]);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
      <Card className="hidden h-fit lg:block">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Contents</CardTitle>
        </CardHeader>
        <CardContent className="max-h-[68vh] overflow-y-auto p-2">
          <nav className="flex flex-col gap-0.5">
            {filteredSections.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => {
                  setActiveId(s.id);
                  document
                    .getElementById(`manual-section-${s.id}`)
                    ?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                className={cnManualToc(activeId === s.id)}
              >
                {s.title}
              </button>
            ))}
            {filteredSections.length === 0 && (
              <div className="px-2 py-1 text-xs italic text-muted">
                {sections.length === 0 ? "No sections parsed." : "No matches."}
              </div>
            )}
          </nav>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookOpen className="h-4 w-4 text-amber" /> UI Manual
            </CardTitle>
            <CardDescription>
              Full reference for every screen in the new UI.
            </CardDescription>
          </div>
          <div className="relative mt-2">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-8 pr-8"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search the manual…"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1 text-muted hover:bg-surfaceAlt"
                aria-label="Clear search"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {manual.isLoading && (
            <div className="flex items-center gap-2 py-6 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading manual…
            </div>
          )}
          {manual.isError && (
            <div className="flex items-center gap-2 py-4 text-sm text-danger">
              <AlertTriangle className="h-4 w-4" />
              {(manual.error as Error).message}
            </div>
          )}
          {manual.data && (
            <>
              {q && (
                <div className="mb-3 text-xs text-muted">
                  Showing {filteredSections.length} of {sections.length} sections
                  matching "{query}".
                </div>
              )}
              {filteredSections.length === 0 && q ? (
                <div className="py-8 text-center text-sm text-muted">
                  No sections match your search.
                </div>
              ) : (
                <div
                  className="max-h-[68vh] overflow-y-auto pr-3 text-sm leading-relaxed [&_a]:text-amber [&_a]:underline-offset-2 [&_a:hover]:underline [&_code]:rounded [&_code]:bg-surfaceAlt [&_code]:px-1 [&_h1]:font-display [&_h1]:text-3xl [&_h1]:mb-4 [&_h1]:mt-2 [&_h2]:font-display [&_h2]:text-2xl [&_h2]:mt-6 [&_h2]:mb-3 [&_h2]:border-b [&_h2]:border-border [&_h2]:pb-1 [&_h3]:font-display [&_h3]:text-xl [&_h3]:mt-4 [&_h3]:mb-2 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-1 [&_p]:my-2 [&_hr]:my-4 [&_hr]:border-border [&_table]:w-full [&_table]:text-xs [&_th]:border-b [&_th]:border-border [&_th]:text-left [&_th]:px-2 [&_th]:py-1 [&_td]:border-b [&_td]:border-border/50 [&_td]:px-2 [&_td]:py-1"
                  dangerouslySetInnerHTML={{ __html: renderedHtml }}
                />
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function cnManualToc(active: boolean): string {
  return active
    ? "rounded-md bg-amber/10 px-2 py-1 text-left text-xs font-semibold text-amber-text"
    : "rounded-md px-2 py-1 text-left text-xs text-muted transition hover:bg-surfaceAlt hover:text-ink";
}

interface TutorialCatalogItem {
  tutorial_id: string;
  title: string;
  summary: string;
  steps: TutorialStep[];
}

function TutorialsTab() {
  const tutorials = useQuery({
    queryKey: ["help-tutorials"],
    queryFn: () => api.helpTutorials(),
  });

  const [active, setActive] = useState<TutorialCatalogItem | null>(null);
  const enabled = useTutorialStore((s) => s.enabled);
  const toggleEnabled = useTutorialStore((s) => s.toggle);
  const restart = useTutorialStore((s) => s.restartAll);

  const items: TutorialCatalogItem[] = tutorials.data?.tutorials ?? [];

  return (
    <>
      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="text-base">First-year tutorials</CardTitle>
          <CardDescription>
            When enabled, each page auto-opens its tutorial the first time
            you visit it. Dismissing a tutorial marks it seen for good;
            "Restart tutorials" rewinds the flags so you can walk the tour
            again.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-amber"
              checked={enabled}
              onChange={(e) => toggleEnabled(e.target.checked)}
            />
            <span>Auto-open tutorials on first visit</span>
          </label>
          <Button variant="outline" size="sm" onClick={restart}>
            Restart tutorials
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <GraduationCap className="h-4 w-4 text-amber" /> Walk-through tutorials
          </CardTitle>
          <CardDescription>
            Short multi-step guides for every major flow. Click any card to
            launch.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {tutorials.isLoading && (
            <div className="flex items-center gap-2 py-6 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading tutorials…
            </div>
          )}
          {tutorials.isError && (
            <div className="flex items-center gap-2 py-4 text-sm text-danger">
              <AlertTriangle className="h-4 w-4" />
              {(tutorials.error as Error).message}
            </div>
          )}
          {items.length > 0 && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((t) => (
                <button
                  key={t.tutorial_id}
                  type="button"
                  onClick={() => setActive(t)}
                  className="group flex flex-col items-start gap-2 rounded-md border border-border bg-surface p-3 text-left transition hover:border-amber hover:bg-surfaceAlt"
                >
                  <div className="flex w-full items-center justify-between gap-2">
                    <span className="font-semibold">{t.title}</span>
                    <Badge tone="amber">{t.steps.length} steps</Badge>
                  </div>
                  <p className="text-xs text-muted">{t.summary}</p>
                  <div className="mt-auto inline-flex items-center gap-1 text-xs text-amber opacity-0 transition group-hover:opacity-100">
                    <PlayCircle className="h-3 w-3" /> Start
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {active && (
        <TutorialDialog
          open={!!active}
          onOpenChange={(open) => !open && setActive(null)}
          title={active.title}
          summary={active.summary}
          steps={active.steps}
        />
      )}
    </>
  );
}

function LegacyManualsTab() {
  const legacyQuery = useQuery({
    queryKey: ["help-legacy"],
    queryFn: () => api.helpLegacyManuals(),
  });
  const token = useAuthStore((s) => s.token);

  async function openManual(docId: string) {
    const { apiBaseUrl, launchToken } = getBridge();
    const authToken = token ?? launchToken;
    const url = api.helpLegacyManualUrl(docId);
    try {
      const res = await fetch(url, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
      });
      if (!res.ok) {
        alert(`Could not open manual: ${res.status}`);
        return;
      }
      const html = await res.text();
      const blob = new Blob([html], { type: "text/html" });
      const objUrl = URL.createObjectURL(blob);
      window.open(objUrl, "_blank", "noopener,noreferrer");
    } catch (err) {
      alert(`Could not open manual: ${(err as Error).message}`);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FileText className="h-4 w-4 text-amber" /> Legacy PyQt-era manuals
        </CardTitle>
        <CardDescription>
          Background reading — deeper dives into gameplay rules and the
          finance system. These open in a new window.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {legacyQuery.isLoading && (
          <div className="flex items-center gap-2 py-3 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        )}
        {(legacyQuery.data?.manuals ?? []).map((m) => (
          <div
            key={m.doc_id}
            className="flex items-center justify-between rounded-md border border-border bg-surface p-3 text-sm"
          >
            <div>
              <div className="font-semibold">
                {LEGACY_MANUAL_LABELS[m.doc_id] ?? m.doc_id}
              </div>
              <div className="text-[11px] text-muted">{m.filename}</div>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => openManual(m.doc_id)}
              disabled={!m.available}
            >
              <ExternalLink className="mr-1 h-4 w-4" />
              {m.available ? "Open" : "Missing"}
            </Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
