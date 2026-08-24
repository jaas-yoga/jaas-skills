import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { auth } from "@/auth";
import { AppShell } from "@/components/shell/app-shell";

export default async function AuthenticatedLayout({ children }: { children: ReactNode }) {
  const session = await auth();
  if (!session) {
    // Defense in depth alongside proxy.ts's redirect — this layout should
    // never actually render for a signed-out request, but never trust a
    // single enforcement point for auth.
    redirect("/login");
  }

  const user = session.runeUser
    ? {
        name: session.runeUser.name,
        email: session.runeUser.email,
        imageUrl: session.runeUser.pictureUrl ?? undefined,
      }
    : undefined;

  return (
    <AppShell user={user} tenants={session.runeTenants} activeTenantId={session.runeActiveTenantId}>
      {children}
    </AppShell>
  );
}
