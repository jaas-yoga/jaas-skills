"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { PRIMARY_NAV } from "./nav-items";
import { TenantSwitcher, type Tenant } from "./tenant-switcher";

export function Sidebar({
  tenants,
  activeTenantId,
}: {
  tenants?: Tenant[];
  activeTenantId?: string;
}) {
  const pathname = usePathname();

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground md:flex">
      <div className="flex h-14 items-center border-b border-sidebar-border px-4">
        <span className="text-sm font-semibold tracking-tight">JaaS Skills</span>
      </div>

      <div className="border-b border-sidebar-border p-3">
        <TenantSwitcher tenants={tenants} activeTenantId={activeTenantId} />
      </div>

      <nav className="flex-1 space-y-1 p-3">
        {PRIMARY_NAV.map((item) => {
          const active = pathname === item.href.split("?")[0];
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              )}
              aria-current={active ? "page" : undefined}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
