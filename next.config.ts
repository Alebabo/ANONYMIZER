import type { NextConfig } from "next";
// Playground CSV uploads go through a server action and the middleware (limit matches the API: 100 MB of CSV).
const nextConfig: NextConfig = { poweredByHeader: false, experimental: { serverActions: { bodySizeLimit: "101mb" }, middlewareClientMaxBodySize: "101mb" } };
export default nextConfig;
