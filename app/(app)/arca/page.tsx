import { PageHeader } from "@/components/app-shell";
import { Notice } from "@/components/dashboard";
import { ARCA_TERMINAL_URL, ArcaError, arca, type ArcaTables } from "@/lib/arca-api";
import { ArcaWorkspace } from "./workspace";

export const dynamic = "force-dynamic";

export default async function ArcaPage() {
  let tables: ArcaTables | null = null;
  let error: string | null = null;
  try {
    tables = await arca<ArcaTables>("/tables");
  } catch (e) {
    if (!(e instanceof ArcaError)) throw e;
    error = e.message;
  }
  return (
    <>
      <PageHeader title="Arca"
                  description="Duale Datenbank: B bleibt vertraulich, Claude liest nur, was du anonymisiert in A freigibst."
                  meta={<span className="bg-light-yellow text-dark-yellow rounded-md px-1.5 py-0.5">Prototyp · Demodaten</span>} />
      <div className="space-y-4 p-4 md:p-6">
        {error && <Notice>{error}</Notice>}
        {tables && <ArcaWorkspace tables={tables} terminalUrl={ARCA_TERMINAL_URL} />}
      </div>
    </>
  );
}
