"use client";

import Editor from "@monaco-editor/react";
import { AlertTriangle, ExternalLink, GitBranch, Loader2, Trash2 } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { CertificationPreview } from "@/components/drafts/certification-preview";
import { FileTree } from "@/components/drafts/file-tree";
import { GuardrailWarningsPanel } from "@/components/drafts/guardrail-warnings-panel";
import { PublishDialog } from "@/components/drafts/publish-dialog";
import { ValidationResultsPanel } from "@/components/drafts/validation-results-panel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  deleteDraftAction,
  deleteDraftFileAction,
  getDraftFileAction,
  moveDraftToGitDirectoryAction,
  saveDraftFileAction,
  validateDraftAction,
} from "@/lib/actions";
import { languageForPath } from "@/lib/monaco-language";
import type { ValidationResultResponse } from "@/lib/rune-api-types";
import { cn } from "@/lib/utils";

type TabStatus = "loading" | "saved" | "dirty" | "saving" | "error";

type Tab = {
  content: string;
  status: TabStatus;
  error?: string;
};

const AUTOSAVE_DELAY_MS = 1500;

/** ui-design.md §11 — the authoring workspace: file tree + Monaco editor +
 * autosave + validate + publish, all against one draft. The debounced
 * autosave only ever writes locally — when the draft is git-connected
 * (drafts/git_sync.py), a commit to `workingBranch` happens only from the
 * explicit "Save Draft" button, which prompts for a commit message first;
 * gitSyncStatus/gitSyncError below reflect the *last* such commit,
 * independent of any single tab's own save status. */
export function DraftWorkspace({
  draftId,
  initialFiles,
  repoUrl,
  targetBranch,
  workingBranch,
  initialGitSyncStatus,
  initialGitSyncError,
  initialGitSubdirectory,
}: {
  draftId: string;
  initialFiles: string[];
  repoUrl?: string | null;
  targetBranch?: string | null;
  workingBranch?: string | null;
  initialGitSyncStatus?: "synced" | "error" | null;
  initialGitSyncError?: string | null;
  initialGitSubdirectory?: string | null;
}) {
  const [files, setFiles] = useState(initialFiles);
  const [tabs, setTabs] = useState<Record<string, Tab>>({});
  const [activePath, setActivePath] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResultResponse | null>(null);
  const [validating, startValidating] = useTransition();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, startDeleting] = useTransition();
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [gitSyncStatus, setGitSyncStatus] = useState(initialGitSyncStatus ?? null);
  const [gitSyncError, setGitSyncError] = useState(initialGitSyncError ?? null);
  const [gitSubdirectory, setGitSubdirectory] = useState(initialGitSubdirectory ?? null);
  const [movingToDirectory, startMovingToDirectory] = useTransition();
  const [moveToDirectoryError, setMoveToDirectoryError] = useState<string | null>(null);
  const [commitDialogOpen, setCommitDialogOpen] = useState(false);
  const [commitMessage, setCommitMessage] = useState("");
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const { resolvedTheme, theme } = useTheme();
  const router = useRouter();

  useEffect(() => {
    // Intentionally reads timers.current at unmount time, not a snapshot
    // from mount — this is a plain mutable timer registry (not a DOM node
    // ref), so we want whichever autosave timers are pending right now,
    // not whatever existed when the component first mounted.
    return () => {
      // eslint-disable-next-line react-hooks/exhaustive-deps
      Object.values(timers.current).forEach(clearTimeout);
    };
  }, []);

  async function openFile(path: string) {
    setActivePath(path);
    if (tabs[path]) return;
    setTabs((prev) => ({ ...prev, [path]: { content: "", status: "loading" } }));
    const content = await getDraftFileAction(draftId, path);
    setTabs((prev) => ({ ...prev, [path]: { content, status: "saved" } }));
  }

  function scheduleSave(path: string, content: string) {
    if (timers.current[path]) clearTimeout(timers.current[path]);
    timers.current[path] = setTimeout(() => saveFile(path, content), AUTOSAVE_DELAY_MS);
  }

  function handleChange(path: string, content: string) {
    setTabs((prev) => ({ ...prev, [path]: { ...prev[path], content, status: "dirty" } }));
    scheduleSave(path, content);
  }

  async function saveFile(
    path: string,
    content: string,
    options?: { syncToGit?: boolean; commitMessage?: string },
  ) {
    setTabs((prev) => ({ ...prev, [path]: { ...prev[path], status: "saving" } }));
    const result = await saveDraftFileAction(draftId, path, content, options);
    if (result.ok) {
      setFiles(result.files);
      setTabs((prev) => ({ ...prev, [path]: { content, status: "saved" } }));
      setGitSyncStatus(result.gitSyncStatus);
      setGitSyncError(result.gitSyncError);
    } else {
      setTabs((prev) => ({ ...prev, [path]: { content, status: "error", error: result.error } }));
    }
  }

  /** "Save Draft" button — the only place that ever commits to GitHub.
   * When the draft is git-connected this pauses for a commit message first;
   * a local-only draft just saves immediately since there's nothing to
   * describe a commit for. */
  function handleSaveDraftClick() {
    if (!activePath || !activeTab) return;
    if (repoUrl) {
      setCommitMessage("");
      setCommitDialogOpen(true);
      return;
    }
    saveFile(activePath, activeTab.content, { syncToGit: true });
  }

  function confirmCommitAndSave() {
    if (!activePath || !activeTab) return;
    saveFile(activePath, activeTab.content, {
      syncToGit: true,
      commitMessage: commitMessage.trim() || undefined,
    });
    setCommitDialogOpen(false);
  }

  /** One-time migration for a draft connected before every skill got its
   * own folder — moves its already-committed files into `<skill-id>/` so
   * this repo can safely host other skills too. */
  function handleMoveToDirectory() {
    setMoveToDirectoryError(null);
    startMovingToDirectory(async () => {
      const result = await moveDraftToGitDirectoryAction(draftId);
      if (result.ok) {
        setGitSubdirectory(result.gitSubdirectory);
        setGitSyncStatus(result.gitSyncStatus);
      } else {
        setMoveToDirectoryError(result.error);
      }
    });
  }

  async function handleCreate(path: string) {
    const result = await saveDraftFileAction(draftId, path, "", { syncToGit: true });
    if (result.ok) {
      setFiles(result.files);
      setTabs((prev) => ({ ...prev, [path]: { content: "", status: "saved" } }));
      setActivePath(path);
    }
  }

  /** Drag-and-drop upload — same write path as handleCreate, but with the
   * dropped file's real content instead of starting it empty. Creating and
   * uploading files are deliberate one-off actions (unlike keystroke-driven
   * autosave), so they still commit immediately rather than waiting for the
   * next explicit Save Draft. */
  async function handleUploadFile(path: string, content: string) {
    const result = await saveDraftFileAction(draftId, path, content, { syncToGit: true });
    if (result.ok) {
      setFiles(result.files);
      setTabs((prev) => ({ ...prev, [path]: { content, status: "saved" } }));
      setActivePath(path);
      setGitSyncStatus(result.gitSyncStatus);
      setGitSyncError(result.gitSyncError);
    }
  }

  async function handleDelete(path: string) {
    const result = await deleteDraftFileAction(draftId, path);
    if (result.ok) {
      setFiles(result.files);
      setTabs((prev) => {
        const next = { ...prev };
        delete next[path];
        return next;
      });
      if (activePath === path) setActivePath(null);
    }
  }

  function handleValidate() {
    startValidating(async () => {
      setValidation(await validateDraftAction(draftId));
    });
  }

  function handleDeleteDraft() {
    setDeleteError(null);
    startDeleting(async () => {
      const result = await deleteDraftAction(draftId);
      if (!result.ok) {
        setDeleteError(result.error);
        return;
      }
      router.push("/drafts");
    });
  }

  function jumpToFile(path: string) {
    if (files.includes(path)) openFile(path);
  }

  const activeTab = activePath ? tabs[activePath] : null;
  const openPaths = Object.keys(tabs);
  const monacoTheme = (resolvedTheme ?? theme) === "light" || theme === "ocean" ? "vs" : "vs-dark";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {repoUrl && workingBranch && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-muted/40 px-3 py-1.5 text-xs">
          <GitBranch className="size-3.5 text-muted-foreground" />
          <span className="font-mono text-muted-foreground">
            {workingBranch} <span className="text-foreground/40">→</span> {targetBranch}
          </span>
          {gitSubdirectory && (
            <span className="rounded bg-background px-1.5 py-0.5 font-mono text-muted-foreground ring-1 ring-border">
              {gitSubdirectory}/
            </span>
          )}
          <span
            className={cn(
              "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
              gitSyncStatus === "error"
                ? "bg-danger/10 text-danger"
                : "bg-success/10 text-success",
            )}
          >
            {gitSyncStatus === "error" ? "Sync error" : "Synced"}
          </span>
          <div className="ml-auto flex items-center gap-3">
            {!gitSubdirectory && (
              <button
                type="button"
                onClick={handleMoveToDirectory}
                disabled={movingToDirectory}
                className="flex items-center gap-1 font-medium text-brand hover:underline disabled:opacity-50"
                title="Move this skill's files into their own folder, so this repo can also host other skills"
              >
                {movingToDirectory ? <Loader2 className="size-3 animate-spin" /> : null}
                Move to directory
              </button>
            )}
            <Link
              href={`${repoUrl}/tree/${workingBranch}`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-brand hover:underline"
            >
              View on GitHub
              <ExternalLink className="size-3" />
            </Link>
          </div>
        </div>
      )}

      {moveToDirectoryError && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-danger/5 px-3 py-1.5 text-xs text-danger">
          <AlertTriangle className="size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate">
            Couldn&apos;t move this skill into a directory — {moveToDirectoryError}
          </span>
          <button
            type="button"
            className="shrink-0 font-medium hover:underline"
            onClick={handleMoveToDirectory}
          >
            Retry
          </button>
        </div>
      )}

      {gitSyncStatus === "error" && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-danger/5 px-3 py-1.5 text-xs text-danger">
          <AlertTriangle className="size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate">Not synced to GitHub — {gitSyncError}</span>
          <button
            type="button"
            className="shrink-0 font-medium hover:underline"
            onClick={() =>
              activePath && activeTab && saveFile(activePath, activeTab.content, { syncToGit: true })
            }
          >
            Retry
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 w-64 shrink-0">
          <FileTree
            files={files}
            activePath={activePath}
            onSelect={openFile}
            onCreate={handleCreate}
            onDelete={handleDelete}
            onUploadFile={handleUploadFile}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          {openPaths.length > 0 && (
            <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-background px-2">
              {openPaths.map((path) => {
                const tab = tabs[path];
                return (
                  <button
                    key={path}
                    type="button"
                    onClick={() => setActivePath(path)}
                    className={cn(
                      "flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 font-mono text-xs",
                      path === activePath
                        ? "border-brand text-foreground"
                        : "border-transparent text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {path}
                    {tab.status === "saving" && <Loader2 className="size-3 animate-spin" />}
                    {tab.status === "dirty" && (
                      <span className="size-1.5 rounded-full bg-warning" title="Unsaved" />
                    )}
                    {tab.status === "error" && (
                      <span title={tab.error ?? "Save failed"}>
                        <AlertTriangle className="size-3 text-danger" />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          <div className="min-h-0 flex-1">
            {activeTab ? (
              activeTab.status === "loading" ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="size-5 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <Editor
                  path={activePath ?? undefined}
                  language={activePath ? languageForPath(activePath) : "plaintext"}
                  value={activeTab.content}
                  onChange={(value) => activePath && handleChange(activePath, value ?? "")}
                  theme={monacoTheme}
                  options={{
                    minimap: { enabled: false },
                    fontSize: 13,
                    fontLigatures: false,
                    automaticLayout: true,
                  }}
                />
              )
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Select a file to start editing, or create a new one.
              </div>
            )}
          </div>
        </div>
      </div>

      {validation && <ValidationResultsPanel result={validation} onJumpToFile={jumpToFile} />}
      {validation && <GuardrailWarningsPanel result={validation} />}
      {validation && <CertificationPreview result={validation} />}

      <div className="flex shrink-0 items-center gap-2 border-t border-border bg-background p-3">
        <Button variant="outline" onClick={handleValidate} disabled={validating}>
          {validating ? <Loader2 className="size-4 animate-spin" /> : null}
          Validate
        </Button>
        <Button
          variant="outline"
          disabled={!activePath || activeTab?.status === "saving"}
          onClick={handleSaveDraftClick}
        >
          Save Draft
        </Button>
        <Button variant="destructive" onClick={() => setConfirmingDelete(true)}>
          <Trash2 className="size-4" />
          Delete Draft
        </Button>
        <div className="flex-1" />
        <PublishDialog
          draftId={draftId}
          canPublish={validation?.valid ?? false}
          workingBranch={workingBranch}
          targetBranch={targetBranch}
        />
      </div>

      <Dialog open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete this draft?</DialogTitle>
            <DialogDescription>
              This discards all of its files. There is no undo — a published skill is
              unaffected either way, since a draft is only ever unpublished scratch space.
            </DialogDescription>
          </DialogHeader>
          {deleteError && <p className="text-sm text-danger">{deleteError}</p>}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmingDelete(false)}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteDraft} disabled={deleting}>
              {deleting ? <Loader2 className="size-4 animate-spin" /> : null}
              Delete Draft
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={commitDialogOpen} onOpenChange={setCommitDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Save and commit to GitHub</DialogTitle>
            <DialogDescription>
              <span className="font-mono">{activePath}</span> will be committed to{" "}
              <span className="font-mono">{workingBranch}</span>. Describe the change:
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            value={commitMessage}
            onChange={(e) => setCommitMessage(e.target.value)}
            placeholder={activePath ? `Update ${activePath}` : "Update file"}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                confirmCommitAndSave();
              }
            }}
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCommitDialogOpen(false)}
              disabled={activeTab?.status === "saving"}
            >
              Cancel
            </Button>
            <Button onClick={confirmCommitAndSave} disabled={activeTab?.status === "saving"}>
              {activeTab?.status === "saving" ? <Loader2 className="size-4 animate-spin" /> : null}
              Commit & Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
