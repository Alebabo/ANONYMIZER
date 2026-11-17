"use client";
import { Upload } from "lucide-react";
import { deleteDataset, uploadDataset } from "@/app/actions";
import { ActionForm, InlineAction, Submit } from "@/components/forms";

// Must match the API limit (playground.MAX_BYTES). Checked in the browser so an oversized file
// never reaches the server action, whose body limit would otherwise answer with a 500.
const MAX_BYTES = 5_000_000;

function checkSize(e: React.ChangeEvent<HTMLInputElement>) {
  const input = e.currentTarget;
  const file = input.files?.[0];
  input.setCustomValidity(file && file.size > MAX_BYTES
    ? `File has ${(file.size / 1_000_000).toFixed(1)} MB, the playground accepts up to 5 MB. Upload a smaller export (fewer days or columns).`
    : "");
  input.reportValidity();
}

export function UploadForm() {
  return (
    <ActionForm action={uploadDataset} className="space-y-2">
      <label className="border-border-contrast hover:bg-muted/50 flex cursor-pointer flex-col items-center gap-1 rounded-md border border-dashed px-3 py-4 text-center text-xs">
        <Upload className="text-muted-foreground h-4 w-4" />
        <span>Choose a CSV file</span>
        <span className="text-muted-foreground text-2xs">Header row · , ; or tab · max 5 MB</span>
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
