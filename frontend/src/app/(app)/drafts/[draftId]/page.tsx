import { notFound } from "next/navigation";

import { DraftWorkspace } from "@/components/drafts/draft-workspace";
import { RuneApiRequestError } from "@/lib/rune-api";
import { getDraft } from "@/lib/drafts-api";

export default async function DraftWorkspacePage({
  params,
}: {
  params: Promise<{ draftId: string }>;
}) {
  const { draftId } = await params;

  const draft = await (async () => {
    try {
      return await getDraft(draftId);
    } catch (err) {
      if (err instanceof RuneApiRequestError && err.status === 404) {
        notFound();
      }
      throw err;
    }
  })();

  return (
    <DraftWorkspace
      draftId={draft.id}
      initialFiles={draft.files}
      repoUrl={draft.repoUrl}
      targetBranch={draft.targetBranch}
      workingBranch={draft.workingBranch}
      initialGitSyncStatus={draft.gitSyncStatus}
      initialGitSyncError={draft.gitSyncError}
      initialGitSubdirectory={draft.gitSubdirectory}
    />
  );
}
