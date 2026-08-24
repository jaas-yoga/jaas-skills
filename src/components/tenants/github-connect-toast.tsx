"use client";

import { useEffect } from "react";
import { toast } from "sonner";

/** Fires once on mount for the `?github=connected|error` redirect back
 * from api/github_routes.py::github_callback — the callback itself can
 * only ever respond with a redirect (no frontend code is running to show
 * it anything richer), so this is where that outcome actually surfaces. */
export function GitHubConnectToast({ status }: { status: "connected" | "error" | null }) {
  useEffect(() => {
    if (status === "connected") {
      toast.success("GitHub connected");
    } else if (status === "error") {
      toast.error("Couldn't connect GitHub — please try again.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
