"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { removeGithubOAuthAppAction, saveGithubOAuthAppAction } from "@/lib/actions";
import type { GithubOAuthAppResponse } from "@/lib/rune-api-types";

/** Each tenant registers its own GitHub OAuth App here — there is no
 * shared, deployment-wide app (authn/github_oauth_apps.py). This gates
 * GitHubConnectionCard below it: "Connect GitHub" only appears once this
 * is saved. Not a bespoke secret-storage UI beyond what a PAT create form
 * already does elsewhere in this app — same posture, write-only secret. */
export function GitHubOAuthAppCard({
  tenantId,
  app,
  isAdmin,
}: {
  tenantId: string;
  app: GithubOAuthAppResponse;
  isAdmin: boolean;
}) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();
  const [removing, startRemoving] = useTransition();
  const router = useRouter();

  function handleSave() {
    if (!clientId.trim() || !clientSecret.trim()) return;
    setError(null);
    startSaving(async () => {
      const result = await saveGithubOAuthAppAction(tenantId, {
        clientId: clientId.trim(),
        clientSecret: clientSecret.trim(),
      });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setClientId("");
      setClientSecret("");
      router.refresh();
    });
  }

  function handleRemove() {
    startRemoving(async () => {
      await removeGithubOAuthAppAction(tenantId);
      router.refresh();
    });
  }

  if (app.configured) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-border p-4">
        <div>
          <p className="text-sm font-medium text-foreground">GitHub OAuth App configured</p>
          <p className="text-xs text-muted-foreground">
            Client ID: <span className="font-mono">{app.clientId}</span>
          </p>
        </div>
        {isAdmin && (
          <Button
            size="sm"
            variant="outline"
            onClick={handleRemove}
            disabled={removing}
          >
            {removing ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
            Remove
          </Button>
        )}
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="rounded-lg border border-border p-4">
        <p className="text-sm font-medium text-foreground">GitHub not set up for this tenant</p>
        <p className="text-xs text-muted-foreground">
          Ask a tenant admin to register a GitHub OAuth App to enable connecting.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-border p-4">
      <div>
        <p className="text-sm font-medium text-foreground">Set up a GitHub OAuth App</p>
        <p className="text-xs text-muted-foreground">
          Create one at{" "}
          <span className="font-mono">github.com/settings/developers</span> → OAuth Apps → New
          OAuth App, using{" "}
          <span className="break-all font-mono text-foreground">{app.redirectUri}</span> as its
          Authorization callback URL. Then paste the Client ID and a generated Client Secret
          below.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Client ID</label>
          <Input value={clientId} onChange={(e) => setClientId(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Client Secret</label>
          <Input
            type="password"
            value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)}
          />
        </div>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      <Button
        size="sm"
        onClick={handleSave}
        disabled={saving || !clientId.trim() || !clientSecret.trim()}
      >
        {saving ? <Loader2 className="size-4 animate-spin" /> : null}
        Save
      </Button>
    </div>
  );
}
