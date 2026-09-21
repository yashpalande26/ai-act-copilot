import { Suspense } from "react";
import { redirect } from "next/navigation";
import { LogOutIcon } from "lucide-react";

import { auth, signOut } from "@/auth";
import { ChatShell } from "@/components/chat/chat-shell";
import { SiteHeader } from "@/components/site-header";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export default async function AppPage() {
  const session = await auth();
  // Middleware already gates this route; this is the defence-in-depth check
  // that doesn't depend on matcher config being correct.
  if (!session?.user?.email) redirect("/signin");

  const email = session.user.email;
  const name = session.user.name?.split(" ")[0] ?? email.split("@")[0];
  const initials = (session.user.name ?? email).slice(0, 2).toUpperCase();

  return (
    <div className="flex h-dvh flex-col">
      <SiteHeader width="narrow">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full"
              aria-label="Account menu"
            >
              <Avatar className="size-8">
                {session.user.image ? (
                  <AvatarImage src={session.user.image} alt="" />
                ) : null}
                <AvatarFallback className="text-xs">{initials}</AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel className="font-normal">
              <p className="text-sm font-medium">{session.user.name ?? "Signed in"}</p>
              <p className="text-muted-foreground truncate text-xs">{email}</p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <form
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/" });
              }}
            >
              <DropdownMenuItem asChild>
                <button type="submit" className="w-full cursor-pointer">
                  <LogOutIcon className="size-4" aria-hidden />
                  Sign out
                </button>
              </DropdownMenuItem>
            </form>
          </DropdownMenuContent>
        </DropdownMenu>
      </SiteHeader>

      {/* Suspense: ChatShell reads ?s= via useSearchParams. */}
      <Suspense fallback={null}>
        <ChatShell userName={name} />
      </Suspense>
    </div>
  );
}
