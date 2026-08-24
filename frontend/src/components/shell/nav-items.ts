import type { LucideIcon } from "lucide-react";
import { FolderKanban, FolderOpen, LayoutGrid, Share2 } from "lucide-react";

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
};

/** ui-design.md §10.1 — global sidebar primary nav. Browse/My Skills/Shared
 * with Me are query-param variants of the single /skills search route
 * (§10.2); Drafts gets its own section since it's not part of that search
 * index (ui-design.md §7 — drafts are explicitly unindexed scratch space). */
export const PRIMARY_NAV: NavItem[] = [
  { label: "Browse", href: "/skills", icon: LayoutGrid },
  { label: "My Skills", href: "/skills?visibility=mine", icon: FolderKanban },
  { label: "Shared with Me", href: "/skills?visibility=shared-with-me", icon: Share2 },
  { label: "Drafts", href: "/drafts", icon: FolderOpen },
];
