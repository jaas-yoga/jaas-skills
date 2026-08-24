"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { publishDraftAction } from "@/lib/actions";

/** ui-design.md §11.3, §10 "PublishDialog". Publishing always requires an
 * explicit visibility choice (default private) — ui-design.md §5.1's rule
 * that a skill is never silently public. When the draft is git-connected,
 * publish additionally merges `workingBranch` into `targetBranch` and cuts
 * a GitHub release before finishing — a DRAFT_GIT_MERGE_CONFLICT leaves
 * that pull request open for manual resolution instead of failing silently. */
export function PublishDialog({
  draftId,
  canPublish,
  workingBranch,
  targetBranch,
}: {
  draftId: string;
  canPublish: boolean;
  workingBranch?: string | null;
  targetBranch?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [visibility, setVisibility] = useState<"public" | "private">("private");
  const [error, setError] = useState<string | null>(null);
  const [conflictPrUrl, setConflictPrUrl] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function handlePublish() {
    setError(null);
    setConflictPrUrl(null);
    startTransition(async () => {
      const result = await publishDraftAction(draftId, visibility);
      if (!result.ok) {
        setError(result.error);
        if (result.code === "DRAFT_GIT_MERGE_CONFLICT" && result.prUrl) {
          setConflictPrUrl(result.prUrl);
        }
        return;
      }
      setOpen(false);
      router.push(`/skills/${result.skill.id}/versions/${result.skill.version}`);
    });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={!canPublish}>Publish Skill</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Publish this skill</DialogTitle>
          <DialogDescription>
            Publishing is immutable — this exact version can never be edited or deleted, only
            superseded by a new version (ui-design.md §11.4).
            {workingBranch && targetBranch && (
              <>
                {" "}
                This will also merge <code className="rounded bg-muted px-1 py-0.5">
                  {workingBranch}
                </code>{" "}
                into{" "}
                <code className="rounded bg-muted px-1 py-0.5">{targetBranch}</code> and create a
                GitHub release.
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground" htmlFor="publish-visibility">
            Visibility
          </label>
          <Select value={visibility} onValueChange={(v) => setVisibility(v as "public" | "private")}>
            <SelectTrigger id="publish-visibility" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="private">Private — only you and your tenant</SelectItem>
              <SelectItem value="public">Public — visible to everyone</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {error && (
          <p className="text-sm text-danger">
            {error}
            {conflictPrUrl && (
              <>
                {" "}
                <a
                  href={conflictPrUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                >
                  Resolve on GitHub
                </a>
                , then publish again.
              </>
            )}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={handlePublish} disabled={pending}>
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            Publish Skill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
