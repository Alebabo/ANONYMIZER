import { AppShell } from "@/components/app-shell";
import { getMe, isDemo } from "@/lib/anonymizer-api";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { data: me } = await getMe();
  return (
    <AppShell
      account={{
        name: me.user?.name ?? me.kind, email: me.user?.email ?? "", role: me.role,
        organization: me.organization.name, demo: isDemo(),
      }}
    >
      {children}
    </AppShell>
  );
}
