import type { MetadataRoute } from "next";

// Web app manifest: gives the Edge app window (scripts/start-app.ps1) its own name and a PNG icon, which the
// Windows taskbar needs (it does not use the SVG favicon).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "OpenAnonymizer",
    short_name: "OpenAnonymizer",
    start_url: "/",
    display: "standalone",
    background_color: "#000000",
    theme_color: "#000000",
    icons: [
      { src: "/brand/anonymizer-app-icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/brand/anonymizer-app-icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
