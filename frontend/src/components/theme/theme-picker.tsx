"use client";

import { Check } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { THEMES, type ThemeName } from "./theme-provider";

const THEME_META: Record<ThemeName, { label: string; description: string }> = {
  light: { label: "Light", description: "Default — bright surface, indigo accent" },
  dark: { label: "Dark", description: "Full dark mode, indigo accent" },
  ocean: { label: "Ocean", description: "Bright surface, teal/cyan accent" },
  violet: { label: "Violet", description: "Dark surface, purple accent" },
};

/**
 * Full theme picker for /account/appearance (ui-design.md §8.5.2). Each card
 * is styled with that theme's own tokens via `data-theme` scoped to the card
 * itself, so switching is a genuine visual preview, not a name in a list.
 */
export function ThemePicker() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  // See theme-toggle.tsx — next-themes' documented SSR-hydration guard.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {THEMES.map((name) => {
        const active = mounted && theme === name;
        return (
          <button
            key={name}
            type="button"
            data-theme={name}
            onClick={() => setTheme(name)}
            aria-pressed={active}
            className={cn(
              "group relative overflow-hidden rounded-lg border bg-background p-4 text-left transition-colors",
              "border-border hover:border-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active && "border-brand ring-2 ring-brand",
            )}
          >
            {active && (
              <span className="absolute right-3 top-3 flex size-5 items-center justify-center rounded-full bg-brand text-brand-foreground">
                <Check className="size-3.5" />
              </span>
            )}
            <div className="mb-3 space-y-2 rounded-md border border-border bg-card p-3">
              <div className="h-2 w-3/5 rounded-full bg-muted-foreground/30" />
              <div className="h-2 w-2/5 rounded-full bg-muted-foreground/20" />
              <Button size="sm" className="pointer-events-none mt-2">
                Publish Skill
              </Button>
            </div>
            <p className="text-sm font-medium text-foreground">{THEME_META[name].label}</p>
            <p className="text-xs text-muted-foreground">{THEME_META[name].description}</p>
          </button>
        );
      })}
    </div>
  );
}
