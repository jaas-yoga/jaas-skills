import { Building2, Globe, Lock, PenLine, Users, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** ui-design.md §5.1/§5.3 — visibility is a property of the skill id;
 * sharing is additive metadata on top of PRIVATE, not its own enum value. */
export type Visibility = "public" | "private";

export type BadgeKind = "public" | "private" | "shared-user" | "shared-tenant" | "draft";

const BADGE_META: Record<
  BadgeKind,
  { label: string; icon: LucideIcon; className: string }
> = {
  public: {
    label: "Public",
    icon: Globe,
    className: "bg-success/10 text-success border-success/20",
  },
  private: {
    label: "Private",
    icon: Lock,
    className: "bg-muted text-muted-foreground border-border",
  },
  "shared-user": {
    label: "Shared with you",
    icon: Users,
    className: "bg-info/10 text-info border-info/20",
  },
  "shared-tenant": {
    label: "Shared with tenant",
    icon: Building2,
    className: "bg-info/10 text-info border-info/20",
  },
  draft: {
    label: "Draft",
    icon: PenLine,
    className: "bg-warning/10 text-warning border-warning/20",
  },
};

/**
 * Semantic visibility/sharing badge (ui-design.md §8.1). Always pairs
 * color + icon + text label — never color alone — so meaning is never
 * ambiguous for color-blind users or when scanning quickly.
 */
export function VisibilityBadge({
  kind,
  label,
  className,
}: {
  kind: BadgeKind;
  /** Override the default label, e.g. `Shared with Acme Corp` instead of
   * the generic "Shared with tenant". */
  label?: string;
  className?: string;
}) {
  const meta = BADGE_META[kind];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        meta.className,
        className,
      )}
    >
      <Icon className="size-3.5" />
      {label ?? meta.label}
    </span>
  );
}
