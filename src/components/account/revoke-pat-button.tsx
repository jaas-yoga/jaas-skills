"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";
import { revokePatAction } from "@/lib/actions";

export function RevokePatButton({ patId }: { patId: string }) {
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Revoke Access"
      disabled={pending}
      onClick={() =>
        startTransition(async () => {
          await revokePatAction(patId);
          router.refresh();
        })
      }
    >
      {pending ? (
        <Loader2 className="size-4 animate-spin" />
      ) : (
        <Trash2 className="size-4 text-danger" />
      )}
    </Button>
  );
}
