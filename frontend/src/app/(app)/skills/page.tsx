import { PackageSearch, Search, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { auth } from "@/auth";
import { VisibilityBadge, type BadgeKind } from "@/components/skills/visibility-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RuneApiRequestError } from "@/lib/rune-api";
import type { SearchResultItem } from "@/lib/rune-api-types";
import { searchSkills } from "@/lib/skills-api";
import {
  matchesVisibilityFilter,
  VISIBILITY_FILTERS,
  type VisibilityFilter,
} from "@/lib/visibility-filter";

function toBadgeKind(
  item: SearchResultItem,
  caller: { userId?: string; tenantId?: string },
): BadgeKind {
  if (item.visibility === "public") return "public";
  if (item.ownerUser === caller.userId) return "private";
  if (item.ownerTenant === caller.tenantId) return "shared-tenant";
  return "shared-user";
}

function isValidFilter(value: string | undefined): value is VisibilityFilter {
  return VISIBILITY_FILTERS.some((f) => f.value === value);
}

export default async function SkillsBrowsePage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const rawVisibility = Array.isArray(params.visibility) ? params.visibility[0] : params.visibility;
  const activeFilter: VisibilityFilter = isValidFilter(rawVisibility) ? rawVisibility : "all";
  const query = Array.isArray(params.query) ? params.query[0] : params.query;
  const category = Array.isArray(params.category) ? params.category[0] : params.category;

  const session = await auth();
  const caller = { userId: session?.runeUser?.id, tenantId: session?.runeActiveTenantId };

  let items: SearchResultItem[] = [];
  let loadError: string | null = null;
  try {
    const result = await searchSkills({ query, category });
    items = result.items.filter((item) => matchesVisibilityFilter(item, activeFilter, caller));
  } catch (err) {
    loadError =
      err instanceof RuneApiRequestError
        ? `${err.code}: ${err.message}`
        : "Could not reach the registry API.";
  }

  return (
    <div className="w-full space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Skills</h1>
          <p className="text-sm text-muted-foreground">
            Discover published skill packages across your tenants.
          </p>
        </div>
        <Button asChild>
          <Link href="/drafts">Create Skill</Link>
        </Button>
      </div>

      <form action="/skills" className="relative w-full max-w-sm">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          name="query"
          defaultValue={query ?? ""}
          placeholder="Search skills…"
          className="pl-8"
          aria-label="Search skills"
        />
        {activeFilter !== "all" && <input type="hidden" name="visibility" value={activeFilter} />}
        {category && <input type="hidden" name="category" value={category} />}
      </form>

      <div className="flex flex-wrap gap-2">
        {VISIBILITY_FILTERS.map((filter) => {
          const qs = new URLSearchParams();
          if (query) qs.set("query", query);
          if (category) qs.set("category", category);
          if (filter.value !== "all") qs.set("visibility", filter.value);
          const href = qs.size > 0 ? `/skills?${qs.toString()}` : "/skills";
          return (
            <Link key={filter.value} href={href}>
              <Badge
                variant={filter.value === activeFilter ? "default" : "outline"}
                className="cursor-pointer px-3 py-1 text-sm font-normal"
              >
                {filter.label}
              </Badge>
            </Link>
          );
        })}
      </div>

      {loadError ? (
        <EmptyState
          icon={TriangleAlert}
          title="Couldn't load skills"
          description={loadError}
          action={
            <Button asChild variant="outline">
              <Link href="/skills">Retry</Link>
            </Button>
          }
        />
      ) : items.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Visibility</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Version</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} className="cursor-pointer">
                  <TableCell className="font-medium text-foreground">
                    <Link
                      href={`/skills/${item.id}/versions/${item.version}`}
                      className="hover:underline"
                    >
                      {item.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <VisibilityBadge kind={toBadgeKind(item, caller)} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">{item.category}</TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground">
                    {item.version}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <EmptyState
          icon={PackageSearch}
          title="No skills match"
          description="Try a different filter, or create your first skill."
          action={
            <Button asChild>
              <Link href="/drafts">Create Your First Skill</Link>
            </Button>
          }
        />
      )}
    </div>
  );
}
