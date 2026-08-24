import { TenantNavTabs } from "@/components/tenants/tenant-nav-tabs";

export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <div className="w-full space-y-6">
      <TenantNavTabs tenantId={id} />
      {children}
    </div>
  );
}
