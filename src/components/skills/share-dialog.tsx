"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { createShareGrantAction, revokeShareGrantAction } from "@/lib/actions";
import type { ShareGrantResponse } from "@/lib/rune-api-types";

/**
 * ui-design.md §10.5. Known simplification vs. the full design: grantees are
 * entered as raw user/tenant ids, not resolved from an email/name-search
 * autocomplete — that needs a user/tenant lookup endpoint Phase 6 doesn't
 * expose yet either. Functionally complete (create/list/revoke, immediate
 * effect), just less friendly to type into than an autocomplete would be.
 */
export function ShareDialog({
  skillId,
  path,
  initialGrants,
}: {
  skillId: string;
  path: string;
  initialGrants: ShareGrantResponse[];
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"user" | "tenant">("user");
  const [granteeId, setGranteeId] = useState("");
  const [permission, setPermission] = useState<"read" | "read_write">("read");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const grants = initialGrants.filter((g) => g.granteeType === tab);

  function handleAdd() {
    if (!granteeId.trim()) return;
    setError(null);
    startTransition(async () => {
      const result = await createShareGrantAction(
        skillId,
        { granteeType: tab, granteeId: granteeId.trim(), permission },
        path,
      );
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setGranteeId("");
      router.refresh();
    });
  }

  function handleRevoke(grantId: string) {
    setError(null);
    startTransition(async () => {
      const result = await revokeShareGrantAction(skillId, grantId, path);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      router.refresh();
    });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">Share</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Share {skillId}</DialogTitle>
          <DialogDescription>
            Grant a specific person or an entire tenant access to this private skill.
          </DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={(v) => setTab(v as "user" | "tenant")}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="user">People</TabsTrigger>
            <TabsTrigger value="tenant">Tenants</TabsTrigger>
          </TabsList>

          <TabsContent value={tab} className="space-y-4 pt-2">
            <div className="flex items-end gap-2">
              <div className="flex-1 space-y-1">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="grantee-id">
                  {tab === "user" ? "User ID" : "Tenant ID"}
                </label>
                <Input
                  id="grantee-id"
                  value={granteeId}
                  onChange={(e) => setGranteeId(e.target.value)}
                  placeholder={tab === "user" ? "usr_..." : "tnt_..."}
                />
              </div>
              <Select
                value={permission}
                onValueChange={(v) => setPermission(v as "read" | "read_write")}
              >
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">Can view</SelectItem>
                  <SelectItem value="read_write">Can view & publish</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleAdd} disabled={pending || !granteeId.trim()} className="w-full">
              {pending ? <Loader2 className="size-4 animate-spin" /> : null}
              Grant Access
            </Button>

            {error && <p className="text-sm text-danger">{error}</p>}

            <div className="space-y-2">
              {grants.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No {tab === "user" ? "people" : "tenants"} have been granted access yet.
                </p>
              ) : (
                grants.map((grant) => (
                  <div
                    key={grant.id}
                    className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
                  >
                    <div>
                      <p className="font-medium text-foreground">{grant.granteeId}</p>
                      <p className="text-xs text-muted-foreground">
                        {grant.permission === "read_write" ? "Can view & publish" : "Can view"}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Revoke Access"
                      disabled={pending}
                      onClick={() => handleRevoke(grant.id)}
                    >
                      <Trash2 className="size-4 text-danger" />
                    </Button>
                  </div>
                ))
              )}
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
