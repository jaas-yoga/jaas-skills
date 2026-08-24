import { redirect } from "next/navigation";

/** ui-design.md §3 sitemap: "/" redirects to "/skills". */
export default function RootPage() {
  redirect("/skills");
}
