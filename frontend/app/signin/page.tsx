import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeftIcon, ClockIcon, MailIcon } from "lucide-react";

import { auth, signIn } from "@/auth";
import { LegalNotice } from "@/components/legal-notice";
import { Wordmark } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";

function GoogleGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="size-[18px]" aria-hidden>
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.57c2.08-1.92 3.28-4.74 3.28-8.09Z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.76c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 1.46 14.97.5 12 .5A11 11 0 0 0 2.18 7.05l3.66 2.84c.87-2.6 3.3-4.14 6.16-4.14Z"
      />
    </svg>
  );
}

/**
 * Shown when no sign-in provider is configured.
 *
 * This is a deployment state, not a user error, so it reads as a calm status
 * message rather than a failure. It never surfaces a raw exception, and it
 * names the exact variables an operator needs without implying the visitor
 * did anything wrong.
 */
function NoProvidersNotice() {
  return (
    <div className="space-y-5">
      <span className="bg-muted text-muted-foreground flex size-11 items-center justify-center rounded-xl">
        <ClockIcon className="size-5" aria-hidden />
      </span>
      <div className="space-y-2.5">
        <h2 className="type-h3">Sign-in is not available yet</h2>
        <p className="type-meta text-muted-foreground">
          This deployment has no sign-in method configured, so there is nothing
          to sign in with right now. Nothing is wrong on your side.
        </p>
      </div>
      <p className="type-micro text-muted-foreground border-border/70 bg-muted/30 rounded-lg border p-3 text-left">
        <span className="text-foreground font-medium">For the operator:</span>{" "}
        set <code className="font-mono">AUTH_GOOGLE_ID</code> and{" "}
        <code className="font-mono">AUTH_GOOGLE_SECRET</code> in{" "}
        <code className="font-mono">.env.local</code>, then restart. See the
        frontend README.
      </p>
    </div>
  );
}

export default async function SignInPage({ searchParams }: PageProps<"/signin">) {
  const session = await auth();
  if (session?.user) redirect("/app");

  const params = await searchParams;
  const callbackUrl =
    typeof params?.callbackUrl === "string" ? params.callbackUrl : "/app";
  const errorParam = typeof params?.error === "string" ? params.error : null;
  const sentTo = typeof params?.sent === "string" ? params.sent : null;

  const googleEnabled = Boolean(
    process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET,
  );
  const magicLinkEnabled = Boolean(
    process.env.AUTH_RESEND_KEY && process.env.AUTH_DB_URL,
  );
  const anyProvider = googleEnabled || magicLinkEnabled;

  return (
    <main className="flex flex-1 flex-col">
      <div className="mx-auto flex w-full max-w-6xl px-6 py-7">
        <Button asChild variant="ghost" size="sm" className="type-meta -ml-3">
          <Link href="/">
            <ArrowLeftIcon className="size-4" aria-hidden /> Back
          </Link>
        </Button>
      </div>

      <div className="flex flex-1 items-start justify-center px-6 pb-24 sm:items-center">
        <div className="w-full max-w-[25rem]">
          <div className="mb-9 flex justify-center">
            <Wordmark />
          </div>

          <div className="border-hairline bg-card rounded-2xl border p-7 shadow-[var(--shadow-md)] sm:p-9">
            {anyProvider ? (
              <>
                <h1 className="type-h2 text-[1.625rem] leading-tight">
                  Sign in
                </h1>
                <p className="type-meta text-muted-foreground mt-2.5">
                  Ask questions about the EU AI Act and get cited answers.
                </p>

                {errorParam ? (
                  <div
                    role="alert"
                    className="border-destructive/25 bg-destructive/[0.07] text-destructive type-meta mt-6 rounded-lg border px-3.5 py-3"
                  >
                    We could not sign you in. Please try again.
                  </div>
                ) : null}

                {sentTo ? (
                  <div
                    role="status"
                    className="border-grounded/25 bg-grounded/[0.07] type-meta mt-6 rounded-lg border px-3.5 py-3"
                  >
                    Check your inbox for a sign-in link.
                  </div>
                ) : null}

                <div className="mt-7 space-y-3.5">
                  {googleEnabled ? (
                    <form
                      action={async () => {
                        "use server";
                        await signIn("google", { redirectTo: callbackUrl });
                      }}
                    >
                      <Button
                        type="submit"
                        variant="outline"
                        className="type-body h-12 w-full justify-center gap-3"
                      >
                        <GoogleGlyph />
                        Continue with Google
                      </Button>
                    </form>
                  ) : null}

                  {googleEnabled && magicLinkEnabled ? (
                    <div className="flex items-center gap-3 py-1.5">
                      <Separator className="flex-1" />
                      <span className="type-micro text-muted-foreground">
                        or
                      </span>
                      <Separator className="flex-1" />
                    </div>
                  ) : null}

                  {magicLinkEnabled ? (
                    <form
                      action={async (formData: FormData) => {
                        "use server";
                        await signIn("resend", {
                          email: String(formData.get("email") ?? ""),
                          redirectTo: callbackUrl,
                        });
                      }}
                      className="space-y-3.5"
                    >
                      <div className="space-y-2">
                        <label htmlFor="email" className="type-meta font-medium">
                          Email
                        </label>
                        <Input
                          id="email"
                          name="email"
                          type="email"
                          required
                          autoComplete="email"
                          placeholder="you@company.com"
                          className="type-body h-12"
                        />
                      </div>
                      <Button type="submit" className="type-body h-12 w-full gap-2.5">
                        <MailIcon className="size-[18px]" aria-hidden />
                        Email me a sign-in link
                      </Button>
                    </form>
                  ) : null}
                </div>
              </>
            ) : (
              <NoProvidersNotice />
            )}
          </div>

          <div className="mt-7 text-center">
            <LegalNotice variant="inline" />
          </div>
        </div>
      </div>
    </main>
  );
}
