import Link from "next/link";
import { ActivityIcon, LogOutIcon } from "lucide-react";

import { signOut } from "@/auth";
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

export type AccountUser = {
  name: string | null;
  email: string;
  image: string | null;
  isAdmin: boolean;
};

/**
 * The account control for the signed-in shell. A server component so the
 * sign-out server action lives here; the client AppShell receives it as a
 * ready element. `compact` is the avatar-only trigger for the top bar;
 * otherwise a full row (avatar, name, email) for the foot of the sidebar.
 */
export function AccountMenu({ user, compact = false }: { user: AccountUser; compact?: boolean }) {
  const initials = (user.name ?? user.email).slice(0, 2).toUpperCase();
  const avatar = (
    <Avatar className="size-8">
      {user.image ? <AvatarImage src={user.image} alt="" /> : null}
      <AvatarFallback className="text-xs">{initials}</AvatarFallback>
    </Avatar>
  );
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {compact ? (
          <Button variant="ghost" size="icon" className="rounded-full" aria-label="Account menu">
            {avatar}
          </Button>
        ) : (
          <button
            type="button"
            aria-label="Account menu"
            className="hover:bg-sidebar-accent focus-visible:ring-ring flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
          >
            {avatar}
            <span className="min-w-0 flex-1">
              <span className="type-meta text-ink block truncate font-medium">
                {user.name ?? "Signed in"}
              </span>
              <span className="type-micro text-ink-faint block truncate">{user.email}</span>
            </span>
          </button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align={compact ? "end" : "start"} side={compact ? "bottom" : "top"} className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="text-sm font-medium">{user.name ?? "Signed in"}</p>
          <p className="text-muted-foreground truncate text-xs">{user.email}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {user.isAdmin ? (
          <>
            <DropdownMenuItem asChild>
              <Link href="/app/admin/traces" className="cursor-pointer">
                <ActivityIcon className="size-4" aria-hidden />
                Admin: query traces
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        ) : null}
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
  );
}
