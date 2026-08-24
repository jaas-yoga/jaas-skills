"use client";

import { GitFork, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { connectGithubAction, disconnectGithubAction } from "@/lib/actions";
import type { GithubConnectionResponse } from "@/lib/rune-api-types";

/** Sits above Connected Repos on the Repositories tab — connecting here is
 * what turns Connect-a-repo's manual URL/branch entry into a live picker
 * (repo-links-editor.tsx). Not configured at all (no GitHub OAuth App set
 * up for this deployment) renders nothing, same "invisible, not broken"
 * posture as every other optional integration here. lucide-react has no
 * "Github" brand icon in this version, hence GitFork instead. */
export function GitHubConnectionCard({
  tenantId,
  connection,
  isAdmin,
}: {
  tenantId: string;
  connection: GithubConnectionResponse;
  isAdmin: boolean;
}) {
  const [connecting, startConnecting] = useTransition();
  const [disconnecting, startDisconnecting] = useTransition();
  const router = useRouter();

  if (!connection.configured) {
    return null;
  }

  function handleConnect() {
    startConnecting(async () => {
      await connectGithubAction(tenantId);
    });
  }

  function handleDisconnect() {
    startDisconnecting(async () => {
      await disconnectGithubAction(tenantId);
      router.refresh();
    });
  }

  if (!connection.connected) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-border p-4">
        <div className="flex items-center gap-3">
          <GitFork className="size-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium text-foreground">GitHub not connected</p>
            <p className="text-xs text-muted-foreground">
              Connect to pick repos and branches from a live list instead of typing them in.
            </p>
          </div>
        </div>
        {isAdmin && (
          <Button size="sm" onClick={handleConnect} disabled={connecting}>
            {connecting ? <Loader2 className="size-4 animate-spin" /> : <GitFork className="size-4" />}
            Connect GitHub
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between rounded-lg border border-border p-4">
      <div className="flex items-center gap-3">
        <Avatar>
          <AvatarImage src={connection.githubAvatarUrl ?? undefined} alt={connection.githubLogin ?? ""} />
          <AvatarFallback>
            <GitFork className="size-4" />
          </AvatarFallback>
        </Avatar>
        <div>
          <p className="text-sm font-medium text-foreground">
            Connected as @{connection.githubLogin}
          </p>
          <p className="text-xs text-muted-foreground">
            Connect-a-repo below can now browse this account&apos;s repos and branches.
          </p>
        </div>
      </div>
      {isAdmin && (
        <Button size="sm" variant="outline" onClick={handleDisconnect} disabled={disconnecting}>
          {disconnecting ? <Loader2 className="size-4 animate-spin" /> : null}
          Disconnect
        </Button>
      )}
    </div>
  );
}
