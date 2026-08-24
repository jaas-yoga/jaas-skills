import { redirect } from "next/navigation";

/** ui-design.md §10.3 overview — the backend already supports a "stable"
 * SemVer alias (design.md §5.2's stable-version resolution), so the
 * overview redirects there rather than needing a new "list versions"
 * endpoint just to find the latest one. */
export default async function SkillOverviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/skills/${id}/versions/stable`);
}
