import { NextResponse } from "next/server";

import { auth } from "@/auth";

/**
 * Next.js 16 renamed Middleware to Proxy (file convention: proxy.ts, same
 * runtime behavior) — see node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md.
 * Redirects unauthenticated requests to /login, matching ui-design.md §3's
 * sitemap: every route except /login and the Auth.js callback itself
 * requires a session.
 */
export default auth((req) => {
  const isAuthRoute = req.nextUrl.pathname.startsWith("/api/auth");
  const isLoginPage = req.nextUrl.pathname === "/login";

  if (isAuthRoute || isLoginPage) {
    return NextResponse.next();
  }

  if (!req.auth) {
    return NextResponse.redirect(new URL("/login", req.nextUrl.origin));
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
