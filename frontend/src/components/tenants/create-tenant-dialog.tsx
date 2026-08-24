"use client";

import { Loader2 } from "lucide-react";
import { useSession } from "next-auth/react";
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
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { createTenantAction } from "@/lib/actions";

export function CreateTenantDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const { update } = useSession();
  const router = useRouter();

  function handleCreate() {
    if (!name.trim()) return;
    setError(null);
    startTransition(async () => {
      const result = await createTenantAction(name.trim());
      if (!result.ok) {
        setError(result.error);
        return;
      }
      // Switch the session into the tenant we just created and administer.
      await update({ tenantId: result.tenant.id });
      setName("");
      onOpenChange(false);
      router.push(`/tenants/${result.tenant.id}/members`);
      router.refresh();
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create Tenant</DialogTitle>
          <DialogDescription>
            You&apos;ll be the admin of this new tenant, able to invite members and share skills
            with it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground" htmlFor="tenant-name">
            Tenant name
          </label>
          <Input
            id="tenant-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Corp"
            autoFocus
          />
        </div>

        {error && <p className="text-sm text-danger">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={pending || !name.trim()}>
            {pending ? <Loader2 className="size-4 animate-spin" /> : null}
            Create Tenant
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
