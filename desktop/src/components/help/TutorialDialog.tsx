/**
 * Multi-step tutorial dialog. Port of ui/tutorial_dialog.py.
 *
 * Renders HTML bodies from the server catalog; the server-side HTML is
 * authored locally so we trust it, but we still pass through DOMPurify
 * as belt-and-braces since it eventually renders via dangerouslySetInnerHTML.
 */

import { useEffect, useState } from "react";
import DOMPurify from "dompurify";
import { ArrowLeft, ArrowRight, X } from "lucide-react";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";

export interface TutorialStep {
  title: string;
  body_html: string;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  summary?: string;
  steps: TutorialStep[];
}

const SANITIZE_CONFIG = {
  ALLOWED_TAGS: [
    "p",
    "b",
    "i",
    "em",
    "strong",
    "ul",
    "ol",
    "li",
    "br",
    "code",
    "a",
    "span",
  ],
  ALLOWED_ATTR: ["href", "title", "target", "rel"],
};

export function TutorialDialog({
  open,
  onOpenChange,
  title,
  summary,
  steps,
}: Props) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (open) setIndex(0);
  }, [open]);

  if (steps.length === 0) return null;
  const current = steps[Math.min(index, steps.length - 1)];
  if (!current) return null;
  const html = DOMPurify.sanitize(current.body_html, SANITIZE_CONFIG);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {summary && <DialogDescription>{summary}</DialogDescription>}
        </DialogHeader>

        <div className="min-h-[220px] space-y-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-amber">
            Step {index + 1} of {steps.length} · {current.title}
          </div>
          <div
            className="prose prose-invert max-w-none text-sm leading-relaxed [&_b]:font-semibold [&_code]:rounded [&_code]:bg-surfaceAlt [&_code]:px-1 [&_li]:my-0.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </div>

        <div className="mt-4 flex items-center justify-between">
          <Button
            variant="ghost"
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            disabled={index === 0}
          >
            <ArrowLeft className="mr-1 h-4 w-4" /> Back
          </Button>
          <div className="flex items-center gap-1">
            {steps.map((_, i) => (
              <span
                key={i}
                className={
                  i === index
                    ? "h-1.5 w-4 rounded-full bg-amber"
                    : "h-1.5 w-1.5 rounded-full bg-border"
                }
              />
            ))}
          </div>
          {index < steps.length - 1 ? (
            <Button onClick={() => setIndex((i) => i + 1)}>
              Next <ArrowRight className="ml-1 h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={() => onOpenChange(false)}>
              <X className="mr-1 h-4 w-4" /> Close
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
