import { GitCommitHorizontal } from "lucide-react";
import { notFound } from "next/navigation";
import Link from "next/link";

import { auth } from "@/auth";
import { CertificationCard } from "@/components/skills/certification-card";
import { ShareDialog } from "@/components/skills/share-dialog";
import { SkillFilesViewer } from "@/components/skills/skill-files-viewer";
import { VisibilityBadge, type BadgeKind } from "@/components/skills/visibility-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createDraftAction } from "@/lib/actions";
import { RuneApiRequestError } from "@/lib/rune-api";
import type { SkillMetadataResponse } from "@/lib/rune-api-types";
import { getSkillMetadata, listShareGrants, listSkillFiles } from "@/lib/skills-api";

function toBadgeKind(
  entry: SkillMetadataResponse,
  caller: { userId?: string; tenantId?: string },
): BadgeKind {
  if (entry.visibility === "public") return "public";
  if (entry.ownerUser === caller.userId) return "private";
  if (entry.ownerTenant === caller.tenantId) return "shared-tenant";
  return "shared-user";
}

export default async function SkillVersionDetailPage({
  params,
}: {
  params: Promise<{ id: string; version: string }>;
}) {
  const { id, version } = await params;

  let entry: SkillMetadataResponse;
  try {
    entry = await getSkillMetadata(id, version);
  } catch (err) {
    if (err instanceof RuneApiRequestError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  const session = await auth();
  const caller = { userId: session?.runeUser?.id, tenantId: session?.runeActiveTenantId };
  const isOwner = caller.userId === entry.ownerUser;
  const grants = isOwner ? await listShareGrants(id) : [];
  const path = `/skills/${id}/versions/${version}`;
  const files = await listSkillFiles(id, version);

  return (
    <div className="flex h-full min-h-0 w-full flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              {entry.name}
            </h1>
            <VisibilityBadge kind={toBadgeKind(entry, caller)} />
          </div>
          <p className="text-sm text-muted-foreground">{entry.description}</p>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">{entry.category}</Badge>
            {entry.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
          </div>
        </div>
        {isOwner && (
          <div className="flex shrink-0 gap-2">
            <form action={createDraftAction.bind(null, { id: entry.id, version: entry.version })}>
              <Button type="submit" variant="outline">
                New Version
              </Button>
            </form>
            <ShareDialog skillId={id} path={path} initialGrants={grants} />
          </div>
        )}
      </div>

      <div className="rounded-md border border-border bg-muted px-4 py-3 text-sm text-muted-foreground">
        This version is published and immutable — it can never be edited or deleted. To make
        changes, use <span className="font-medium text-foreground">New Version</span> to fork it
        into an editable draft (ui-design.md §11.4).
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Runtime compatibility</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-sm">
            {entry.runtime.map((rt) => (
              <div key={rt.family} className="flex justify-between text-muted-foreground">
                <span className="font-medium text-foreground">{rt.family}</span>
                <span className="font-mono text-xs">{rt.versionRange}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Dependencies</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-sm">
            {entry.dependencies.length === 0 ? (
              <p className="text-muted-foreground">No dependencies.</p>
            ) : (
              entry.dependencies.map((dep) => (
                <div key={dep.id} className="flex justify-between text-muted-foreground">
                  <Link href={`/skills/${dep.id}/versions/stable`} className="hover:underline">
                    {dep.id}
                  </Link>
                  <span className="font-mono text-xs">
                    {dep.versionConstraint}
                    {dep.resolvedVersion ? ` → ${dep.resolvedVersion}` : " (unresolved)"}
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-sm text-muted-foreground">
            <div className="flex justify-between">
              <span>Version</span>
              <span className="font-mono text-xs text-foreground">{entry.version}</span>
            </div>
            <div className="flex justify-between">
              <span>Digest</span>
              <span className="max-w-[60%] truncate font-mono text-xs text-foreground">
                {entry.digest}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Owner team</span>
              <span className="text-foreground">{entry.owner.team}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {entry.sourceRepo && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <GitCommitHorizontal className="size-4 text-muted-foreground" />
              Provenance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-sm text-muted-foreground">
            <p className="mb-2 text-xs">
              Released from git via CI — guardrails were enforced with no opt-out on this path.
            </p>
            <div className="flex justify-between">
              <span>Repo</span>
              <span className="font-mono text-xs text-foreground">{entry.sourceRepo}</span>
            </div>
            {entry.sourceTag && (
              <div className="flex justify-between">
                <span>Tag</span>
                <span className="font-mono text-xs text-foreground">{entry.sourceTag}</span>
              </div>
            )}
            {entry.sourceBranch && (
              <div className="flex justify-between">
                <span>Branch</span>
                <span className="font-mono text-xs text-foreground">{entry.sourceBranch}</span>
              </div>
            )}
            {entry.sourceCommit && (
              <div className="flex justify-between">
                <span>Commit</span>
                <span className="font-mono text-xs text-foreground">{entry.sourceCommit}</span>
              </div>
            )}
            {entry.ciRunUrl && (
              <div className="flex justify-between">
                <span>CI run</span>
                <a
                  href={entry.ciRunUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="max-w-[60%] truncate font-mono text-xs text-foreground hover:underline"
                >
                  {entry.ciRunUrl}
                </a>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <CertificationCard entry={entry} />

      <SkillFilesViewer
        skillId={id}
        version={version}
        files={files}
        hasSourceRepo={Boolean(entry.sourceRepo && (entry.sourceCommit || entry.sourceTag))}
      />
    </div>
  );
}
