import type { SearchResultItem } from "./rune-api-types";

/** ui-design.md §10.2 filter chips. */
export type VisibilityFilter = "all" | "public" | "mine" | "tenant" | "shared-with-me";

export const VISIBILITY_FILTERS: { value: VisibilityFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "public", label: "Public" },
  { value: "mine", label: "My Skills" },
  { value: "shared-with-me", label: "Shared with me" },
  { value: "tenant", label: "My Tenant" },
];

/**
 * The backend's visibility rule (design.md §7.2 item 4) tells us an item IS
 * visible, never *why* — there's no "reason" field in SearchResultItem. The
 * "Shared with me" chip is derived client-side from what we already know: if
 * an already-visible item is private, and I don't own it, and it isn't
 * owned by my own tenant, the only remaining way design.md's rule could have
 * let it through is an explicit share grant naming me or my tenant.
 */
export function matchesVisibilityFilter(
  item: SearchResultItem,
  filter: VisibilityFilter,
  caller: { userId?: string; tenantId?: string },
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "public":
      return item.visibility === "public";
    case "mine":
      return item.ownerUser === caller.userId;
    case "tenant":
      return item.ownerTenant === caller.tenantId;
    case "shared-with-me":
      return (
        item.visibility === "private" &&
        item.ownerUser !== caller.userId &&
        item.ownerTenant !== caller.tenantId
      );
  }
}
