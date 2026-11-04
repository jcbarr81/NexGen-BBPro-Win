/**
 * "Columns" menu for a player table (backlog #69, 8.10.0): tick the
 * columns to show; the choice is kept per table (see
 * ``lib/rating-columns.ts``). The menu stays open while ticking.
 */

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, Columns3 } from "lucide-react";

import { cn } from "@/lib/cn";
import type { ColumnChoice, ColumnDef } from "@/lib/rating-columns";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";

export function ColumnPicker<C extends ColumnDef>({
  choice,
  className,
}: {
  choice: ColumnChoice<C>;
  className?: string;
}) {
  const groups: Array<{ name: string; items: C[] }> = [];
  for (const col of choice.catalog) {
    const name = col.group ?? "";
    let g = groups.find((x) => x.name === name);
    if (!g) {
      g = { name, items: [] };
      groups.push(g);
    }
    g.items.push(col);
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={className}
          title="Choose which columns this table shows"
        >
          <Columns3 className="h-3.5 w-3.5" /> Columns
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[70vh] overflow-y-auto">
        {groups.map((g, i) => (
          <div key={g.name || i}>
            {i > 0 && <DropdownMenuSeparator />}
            {g.name && <DropdownMenuLabel>{g.name}</DropdownMenuLabel>}
            {g.items.map((col) => {
              const shown = choice.isShown(col.key);
              const last = shown && choice.columns.length <= 1;
              return (
                <DropdownMenuPrimitive.CheckboxItem
                  key={col.key}
                  checked={shown}
                  disabled={last}
                  onCheckedChange={() => choice.toggle(col.key)}
                  // Keep the menu open so several columns can be ticked.
                  onSelect={(e) => e.preventDefault()}
                  className={cn(
                    "flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink outline-none transition",
                    "data-[highlighted]:bg-surfaceAlt",
                    "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                  )}
                >
                  <span className="flex h-4 w-4 items-center justify-center rounded border border-border">
                    <DropdownMenuPrimitive.ItemIndicator>
                      <Check className="h-3 w-3 text-amber" />
                    </DropdownMenuPrimitive.ItemIndicator>
                  </span>
                  <span className="w-10 font-semibold tabular-nums">{col.label}</span>
                  {col.name && <span className="text-muted">{col.name}</span>}
                </DropdownMenuPrimitive.CheckboxItem>
              );
            })}
          </div>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={choice.isDefault}
          onSelect={() => choice.reset()}
        >
          Reset to default
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
