import { KeyRound } from "lucide-react";

import { CreatePatDialog } from "@/components/account/create-pat-dialog";
import { RevokePatButton } from "@/components/account/revoke-pat-button";
import { EmptyState } from "@/components/ui/empty-state";
import { listPats } from "@/lib/account-api";

export default async function TokensPage() {
  const tokens = await listPats();

  return (
    <div className="w-full space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Personal Access Tokens
          </h1>
          <p className="text-sm text-muted-foreground">
            For using <code className="font-mono text-xs">runectl</code> from the command line.
          </p>
        </div>
        <CreatePatDialog />
      </div>

      {tokens.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          title="No tokens yet"
          description="Create one to authenticate runectl from a machine without a browser."
          action={<CreatePatDialog />}
        />
      ) : (
        <div className="divide-y divide-border rounded-lg border border-border">
          {tokens.map((token) => (
            <div key={token.id} className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-sm font-medium text-foreground">{token.name}</p>
                <p className="text-xs text-muted-foreground">
                  Created {new Date(token.createdAt).toLocaleDateString()} · Expires{" "}
                  {new Date(token.expiresAt).toLocaleDateString()}
                </p>
              </div>
              <RevokePatButton patId={token.id} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
