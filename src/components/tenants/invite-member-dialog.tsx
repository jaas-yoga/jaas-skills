"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { inviteMemberAction } from "@/lib/actions";

/** ui-design.md §10.6/Phase 6. Inviting someone who hasn't signed in yet
 * stores a pending invite, resolved automatically the first time they sign
 * in with that Google account (authn/service.py). */
export function InviteMemberDialog({ tenantId }: { tenantId: string }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function handleInvite() {
    if (!email.trim()) return;
    setError(null);
    startTransition(async () => {
      const result = await inviteMemberAction(tenantId, email.trim(), role);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setStatus(
        result.invite.status === "added"
          ? `${result.invite.email} was added immediately.`
          : `${result.invite.email} will join automatically once they sign in.`,
      );
      setEmail("");
      router.refresh();
    });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setStatus(null);
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button>Invite Member</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a member</DialogTitle>
          <DialogDescription>
            If they already have an account, they&apos;re added immediately. Otherwise the invite
            resolves automatically on their first sign-in.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-end gap-2">
          <div className="flex-1 space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="invite-email">
              Email
            </label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="teammate@example.com"
              autoFocus
            />
          </div>
          <Select value={role} onValueChange={(v) => setRole(v as "admin" | "member")}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="member">Member</SelectItem>
              <SelectItem value="admin">Admin</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {status && <p className="text-sm text-success">{status}</p>}
        {error && <p className="text-sm text-danger">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Done
          </Button>
          <Button onClick={handleInvite} disabled={pending || !email.trim()}>
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            Send Invite
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
