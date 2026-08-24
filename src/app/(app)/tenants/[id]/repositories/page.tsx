import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { GitHubConnectToast } from "@/components/tenants/github-connect-toast";
import { GitHubConnectionCard } from "@/components/tenants/github-connection-card";
import { GitHubOAuthAppCard } from "@/components/tenants/github-oauth-app-card";
import { RepoLinksEditor } from "@/components/tenants/repo-links-editor";
import { getGithubConnection, getGithubOAuthApp } from "@/lib/github-api";
import { listRepoLinks } from "@/lib/repo-links-api";
import { RuneApiRequestError } from "@/lib/rune-api";
import { listMembers } from "@/lib/tenants-api";

/** Split out of the Guardrails tab: connecting GitHub and registering which
 * repos may publish/release this tenant's skills isn't a guardrail setting
 * — it's its own tab alongside Members and Guardrails. */
export default async function TenantRepositoriesPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ github?: string }>;
}) {
  const { id } = await params;
  const { github } = await searchParams;

  let members, repoLinks, githubConnection, githubOAuthApp;
  try {
    [members, repoLinks, githubConnection, githubOAuthApp] = await Promise.all([
      listMembers(id),
      listRepoLinks(id),
      getGithubConnection(id),
      getGithubOAuthApp(id),
    ]);
  } catch (err) {
    if (err instanceof RuneApiRequestError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  const session = await auth();
  const me = members.find((m) => m.userId === session?.runeUser?.id);
  const isAdmin = me?.role === "admin";

  return (
    <div className="space-y-6">
      <GitHubConnectToast
        status={github === "connected" || github === "error" ? github : null}
      />

      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Repositories</h1>
        <p className="text-sm text-muted-foreground">
          Connect GitHub, then register which repos may publish drafts or release this
          tenant&apos;s skills from CI.
        </p>
      </div>

      <div className="space-y-4">
        <GitHubOAuthAppCard tenantId={id} app={githubOAuthApp} isAdmin={isAdmin} />
        <GitHubConnectionCard tenantId={id} connection={githubConnection} isAdmin={isAdmin} />
        <RepoLinksEditor
          tenantId={id}
          links={repoLinks}
          githubConnected={githubConnection.connected}
          isAdmin={isAdmin}
        />
      </div>
    </div>
  );
}
