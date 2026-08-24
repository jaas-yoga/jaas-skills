import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { InviteMemberDialog } from "@/components/tenants/invite-member-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { RuneApiRequestError } from "@/lib/rune-api";
import type { MemberResponse } from "@/lib/rune-api-types";
import { listMembers } from "@/lib/tenants-api";

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

export default async function TenantMembersPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let members: MemberResponse[];
  try {
    members = await listMembers(id);
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
    <div className="w-full space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Members</h1>
          <p className="text-sm text-muted-foreground">Who belongs to this tenant.</p>
        </div>
        {isAdmin && <InviteMemberDialog tenantId={id} />}
      </div>

      <div className="divide-y divide-border rounded-lg border border-border">
        {members.map((member) => (
          <div key={member.userId} className="flex items-center justify-between px-4 py-3">
            <div className="flex items-center gap-3">
              <Avatar className="size-8">
                <AvatarFallback>{initials(member.name)}</AvatarFallback>
              </Avatar>
              <div>
                <p className="text-sm font-medium text-foreground">{member.name}</p>
                <p className="text-xs text-muted-foreground">{member.email}</p>
              </div>
            </div>
            <Badge variant={member.role === "admin" ? "default" : "outline"}>{member.role}</Badge>
          </div>
        ))}
      </div>
    </div>
  );
}
