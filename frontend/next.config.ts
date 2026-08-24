import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disambiguate the workspace root: an unrelated empty package-lock.json in
  // the user's home directory would otherwise get inferred as the root.
  turbopack: {
    root: path.join(__dirname),
  },
  // The dev-only route indicator badge (bottom-left "N") — not app UI, just
  // Next's own dev-mode overlay; gone in production builds regardless.
  devIndicators: false,
  experimental: {
    serverActions: {
      // Local dev is sometimes reached through a port-forwarding proxy (e.g.
      // an IDE's preview browser) that presents the page's Origin without
      // its port even though it forwards x-forwarded-host with the port —
      // Next's Server Actions CSRF check rejects that mismatch by default,
      // so the bare hostnames need to be allow-listed alongside the normal
      // host:port form.
      allowedOrigins: ["127.0.0.1", "127.0.0.1:3027", "localhost", "localhost:3027"],
    },
  },
};

export default nextConfig;
