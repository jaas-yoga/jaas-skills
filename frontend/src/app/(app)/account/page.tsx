import { KeyRound, Palette } from "lucide-react";
import Link from "next/link";

import { auth } from "@/auth";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function initials(name: string): string {
  return (
    name
      .split(" ")
      .map((p) => p[0])
      .slice(0, 2)
      .join("")
      .toUpperCase() || "?"
  );
}

/** ui-design.md §10.1 "/account" — profile from the real Google sign-in
 * session (Phase 1) plus tenant memberships (Phase 6). */
export default async function AccountPage() {
  const session = await auth();
  const user = session?.runeUser;

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Account</h1>
        <p className="text-sm text-muted-foreground">
          Profile and tenant memberships, from your Google sign-in.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Profile</CardTitle>
          </CardHeader>
          <CardContent>
            {user ? (
              <div className="flex items-center gap-3">
                <Avatar className="size-10">
                  <AvatarImage src={user.pictureUrl ?? undefined} alt={user.name} />
                  <AvatarFallback>{initials(user.name)}</AvatarFallback>
                </Avatar>
                <div>
                  <p className="text-sm font-medium text-foreground">{user.name}</p>
                  <p className="text-xs text-muted-foreground">{user.email}</p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Not signed in.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tenants</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {session?.runeTenants?.length ? (
              session.runeTenants.map((tenant) => (
                <Link
                  key={tenant.id}
                  href={`/tenants/${tenant.id}/members`}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm hover:border-brand"
                >
                  <span
                    className={
                      tenant.id === session.runeActiveTenantId
                        ? "font-medium text-foreground"
                        : "text-foreground"
                    }
                  >
                    {tenant.name}
                  </span>
                  <Badge variant={tenant.role === "admin" ? "default" : "outline"}>
                    {tenant.role}
                  </Badge>
                </Link>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No tenant memberships yet.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex gap-2">
        <Button asChild variant="outline">
          <Link href="/account/appearance">
            <Palette className="size-4" /> Appearance
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/account/tokens">
            <KeyRound className="size-4" /> Personal Access Tokens
          </Link>
        </Button>
      </div>
    </div>
  );
}
