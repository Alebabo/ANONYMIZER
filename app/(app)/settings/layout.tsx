import { PageHeader } from "@/components/app-shell";
import { SettingsTabs } from "@/app/(app)/settings/tabs";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Settings" description="Organization, members and audit log" />
      <SettingsTabs />
      {children}
    </>
  );
}
