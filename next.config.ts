import type { NextConfig } from "next";
// Playground CSV uploads go through a server action (limit matches the API: 5 MB of CSV text).
const nextConfig: NextConfig = { poweredByHeader: false, experimental: { serverActions: { bodySizeLimit: "6mb" } } };
export default nextConfig;
