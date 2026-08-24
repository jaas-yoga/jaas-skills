"use client";

import { Check, Copy, Loader2 } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { createPatAction } from "@/lib/actions";

/** ui-design.md §4.4/§8.4 — the raw token is shown exactly once, the
 * standard convention for personal access tokens (GitHub/GitLab do the
 * same): there is no "view it again later" path, only revoke-and-reissue. */
export function CreatePatDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function handleCreate() {
    if (!name.trim()) return;
    setError(null);
    startTransition(async () => {
      const result = await createPatAction(name.trim());
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setToken(result.pat.token);
    });
  }

  function handleClose(next: boolean) {
    setOpen(next);
    if (!next) {
      setName("");
      setToken(null);
      setCopied(false);
      setError(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogTrigger asChild>
        <Button>Create Token</Button>
      </DialogTrigger>
      <DialogContent>
        {token ? (
          <>
            <DialogHeader>
              <DialogTitle>Copy your token now</DialogTitle>
              <DialogDescription>
                This is the only time it will be shown. Store it somewhere safe — for example,{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  export RUNE_TOKEN=...
                </code>
                .
              </DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2">
              <code className="flex-1 truncate font-mono text-xs">{token}</code>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Copy token"
                onClick={() => {
                  navigator.clipboard.writeText(token);
                  setCopied(true);
                }}
              >
                {copied ? (
                  <Check className="size-4 text-success" />
                ) : (
                  <Copy className="size-4" />
                )}
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={() => handleClose(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Create a personal access token</DialogTitle>
              <DialogDescription>
                For using <code className="font-mono text-xs">runectl</code> from a machine
                without a browser. It carries the same access your current session has.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="pat-name">
                Name
              </label>
              <Input
                id="pat-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="laptop CLI"
                autoFocus
              />
            </div>
            {error && <p className="text-sm text-danger">{error}</p>}
            <DialogFooter>
              <Button variant="outline" onClick={() => handleClose(false)} disabled={pending}>
                Cancel
              </Button>
              <Button onClick={handleCreate} disabled={pending || !name.trim()}>
                {pending ? <Loader2 className="size-4 animate-spin" /> : null}
                Create Token
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
