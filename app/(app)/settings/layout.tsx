import { PageHeader } from "@/components/app-shell";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader section="settings" title="Settings" description="Organization, members, policies and audit log" />
      {children}
    </>
  );
}
