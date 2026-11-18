import type { NextConfig } from "next";
// Playground CSV uploads go through a server action and the middleware (limit matches the API: 100 MB of CSV).
const nextConfig: NextConfig = {
  poweredByHeader: false,
  experimental: {
    serverActions: { bodySizeLimit: "101mb" }, middlewareClientMaxBodySize: "101mb",
    // Reuse a visited page for 30 s when switching back to it; server actions still refresh it right away.
    staleTimes: { dynamic: 30 },
  },
  // Pages folded into others when the navigation was simplified; keep old bookmarks working.
  redirects: async () => [
    { source: "/metrics", destination: "/", permanent: false },
    { source: "/privacy", destination: "/", permanent: false },
    { source: "/policies", destination: "/settings/policies", permanent: false },
  ],
};
export default nextConfig;
