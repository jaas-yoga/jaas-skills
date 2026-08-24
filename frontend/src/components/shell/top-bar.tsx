"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AccountMenu, type AccountUser } from "@/components/shell/account-menu";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Input } from "@/components/ui/input";

/** Global quick-search: submits to /skills?query=... (Enter), and ⌘K/Ctrl+K
 * from anywhere in the app focuses it, matching the placeholder's own
 * promise. Not a live-filter of the current page — /skills does that
 * itself once you land there with a query. */
export function TopBar({ user }: { user?: AccountUser }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    router.push(trimmed ? `/skills?query=${encodeURIComponent(trimmed)}` : "/skills");
  }

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-4">
      <form onSubmit={handleSubmit} className="relative w-full max-w-sm">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={inputRef}
          type="search"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Search skills… (⌘K)"
          className="pl-8"
          aria-label="Search skills"
        />
      </form>
      <div className="ml-auto flex items-center gap-1.5">
        <ThemeToggle />
        <AccountMenu user={user} />
      </div>
    </header>
  );
}
