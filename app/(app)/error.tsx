"use client";
import { Button } from "@/components/ui/button";

export default function WorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="space-y-3 p-4 md:p-6">
      <h1 className="text-lg font-bold">OpenAnonymizer API error</h1>
      <p className="text-muted-foreground text-sm">
        {process.env.NODE_ENV === "development" ? error.message : "The OpenAnonymizer API did not answer as expected."}
        {error.digest && <span className="font-mono"> · {error.digest}</span>}
      </p>
      <Button variant="outline" onClick={reset}>Try again</Button>
    </div>
  );
}
