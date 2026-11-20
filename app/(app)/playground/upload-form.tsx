"use client";
import { Columns3, Upload } from "lucide-react";
import { deleteDataset, setHiddenColumns, uploadDataset } from "@/app/actions";
import { ActionForm, InlineAction, Submit } from "@/components/forms";

// Must match the API limit (playground.MAX_BYTES). Checked in the browser so an oversized file
// never reaches the server action, whose body limit would otherwise answer with a 500.
const MAX_BYTES = 100 * 1024 * 1024;

function checkSize(e: React.ChangeEvent<HTMLInputElement>) {
  const input = e.currentTarget;
  const file = input.files?.[0];
  input.setCustomValidity(file && file.size > MAX_BYTES
    ? `File has ${(file.size / 1024 / 1024).toFixed(1)} MB, the playground accepts up to 100 MB. Upload a smaller export (fewer days or columns).`
    : "");
  input.reportValidity();
}

export function UploadForm() {
  return (
    <ActionForm action={uploadDataset} className="space-y-2">
      <label className="border-border-contrast hover:bg-muted/50 flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed px-3 py-4 text-center text-xs">
        <Upload className="text-muted-foreground h-4 w-4" />
        <span>Choose a CSV file</span>
        <span className="text-muted-foreground text-2xs">Header row · , ; or tab · max 100 MB · e.g. a sessions export</span>
        <input type="file" name="file" accept=".csv,text/csv,text/plain" required onChange={checkSize}
               className="file:bg-muted mt-1 w-full text-2xs file:mr-2 file:rounded-sm file:border-0 file:px-2 file:py-1" />
      </label>
      <Submit size="sm" className="w-full" pendingText="Uploading…">Upload</Submit>
    </ActionForm>
  );
}

export function DeleteDataset({ id }: { id: string }) {
  return <InlineAction action={deleteDataset} fields={{ id }} label="Delete" variant="ghost"
                       confirm="Delete this dataset? The uploaded rows are removed from the playground store." />;
}

/** Choose which columns are visible. Hidden ones are left out everywhere, including Claude's MCP queries. */
export function ColumnPicker({ id, columns, hidden }: { id: string; columns: string[]; hidden: string[] }) {
  const off = new Set(hidden);
  return (
    <details className="relative">
      <summary className="border-input bg-background hover:bg-muted/50 inline-flex h-8 cursor-pointer list-none items-center gap-1.5 rounded-md border px-3 text-sm [&::-webkit-details-marker]:hidden">
        <Columns3 className="h-3.5 w-3.5" />Columns{hidden.length ? ` (${hidden.length} hidden)` : ""}
      </summary>
      <div className="bg-popover text-popover-foreground absolute right-0 z-20 mt-1 w-64 rounded-lg border p-3 shadow-md">
        <ActionForm action={setHiddenColumns} keepValues className="space-y-2">
          <input type="hidden" name="id" value={id} />
          <p className="text-muted-foreground text-2xs">Unticked columns are not shown, searched or sent to Claude. The upload keeps them.</p>
          <ul className="max-h-64 space-y-1 overflow-auto">
            {columns.map(c => (
              <li key={c}>
                <input type="hidden" name="column" value={c} />
                <label className="flex items-center gap-2 text-xs">
                  <input type="checkbox" name="show" value={c} defaultChecked={!off.has(c)} />
                  <span className="truncate font-mono" title={c}>{c}</span>
                </label>
              </li>
            ))}
          </ul>
          <Submit size="sm" className="w-full" pendingText="Saving…">Apply</Submit>
        </ActionForm>
      </div>
    </details>
  );
}
