"use client";

import { PlusIcon, XIcon } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";
import { fieldBase } from "@/components/ui/input";

/**
 * A list of short values typed one at a time (Enter or comma adds, Backspace on an empty
 * input removes the last). Optional suggestions appear as one-click additions.
 */
export function TagInput({
  id,
  value,
  onChange,
  placeholder,
  suggestions = [],
  disabled,
  mono = false,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
  disabled?: boolean;
  mono?: boolean;
  "aria-label"?: string;
}) {
  const [draft, setDraft] = React.useState("");
  const add = (raw: string) => {
    const v = raw.trim();
    if (!v || value.includes(v)) return;
    onChange([...value, v]);
  };
  const remaining = suggestions.filter((s) => !value.includes(s));
  return (
    <div className="space-y-2">
      <div className={cn(fieldBase, "flex min-h-9 flex-wrap items-center gap-1.5 px-2 py-1.5", disabled && "opacity-60")}>
        {value.map((v) => (
          <span key={v} className={cn("inline-flex h-6 items-center gap-1 rounded-md bg-muted pr-1 pl-2 text-[12.5px]", mono && "font-mono text-[12px]")}>
            {v}
            {!disabled && (
              <button
                type="button"
                aria-label={`Remove ${v}`}
                onClick={() => onChange(value.filter((x) => x !== v))}
                className="flex size-4 items-center justify-center rounded text-subtle hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
              >
                <XIcon className="size-3" />
              </button>
            )}
          </span>
        ))}
        <input
          id={id}
          aria-label={ariaLabel}
          value={draft}
          disabled={disabled}
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => {
            const next = e.target.value;
            if (next.includes(",")) {
              next.split(",").forEach(add);
              setDraft("");
            } else setDraft(next);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
              setDraft("");
            } else if (e.key === "Backspace" && !draft && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={() => {
            if (draft.trim()) {
              add(draft);
              setDraft("");
            }
          }}
          className={cn("h-6 min-w-24 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-faint", mono && "font-mono text-[13px]")}
        />
      </div>
      {!disabled && remaining.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {remaining.slice(0, 24).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => add(s)}
              className={cn(
                "inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[12px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
                mono && "font-mono text-[11.5px]",
              )}
            >
              <PlusIcon className="size-3" />
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
