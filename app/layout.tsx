import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Cato — Privacy Gateway", description: "A privacy layer between sensitive documents and AI agents." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="de"><body>{children}</body></html>; }
