import Link from "next/link";
import { LoginForm } from "@/app/login/form";
import { Wordmark } from "@/components/logo";
import { Card, CardContent } from "@/components/ui/card";
import { isDemo } from "@/lib/cato-api";

export const dynamic = "force-dynamic";

export default async function Login({ searchParams }: { searchParams: Promise<{ next?: string; expired?: string }> }) {
  const { next = "/", expired } = await searchParams;
  return (
    <main className="bg-surface-sunken flex min-h-dvh items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4">
        <div className="flex justify-center"><Wordmark /></div>
        <Card>
          <CardContent className="space-y-4 p-6">
            <div>
              <h1 className="text-lg font-bold">Sign in</h1>
              <p className="text-muted-foreground text-xs">Privacy infrastructure for legal AI</p>
            </div>
            {isDemo() ? (
              <p className="text-sm">
                Demo mode: no API connected, so there is nothing to sign in to.{" "}
                <Link href="/" className="text-link hover:text-link-hover">Open the demo dashboard</Link>.
              </p>
            ) : (
              <>
                {expired && <p className="bg-light-yellow text-dark-yellow rounded-md px-2 py-1 text-xs">Your session has expired.</p>}
                <LoginForm next={next} />
              </>
            )}
          </CardContent>
        </Card>
        <p className="text-muted-foreground text-center text-2xs">
          Accounts are created by an administrator (<code>cato user create</code> or Settings → Members).
        </p>
      </div>
    </main>
  );
}
