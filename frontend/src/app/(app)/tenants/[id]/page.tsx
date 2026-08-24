import { redirect } from "next/navigation";

export default async function TenantHomePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/tenants/${id}/members`);
}
