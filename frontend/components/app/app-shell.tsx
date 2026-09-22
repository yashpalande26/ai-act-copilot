"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ActivityIcon,
  ClipboardCheckIcon,
  MenuIcon,
  MessageSquareTextIcon,
  XIcon,
} from "lucide-react";

import { Wordmark } from "@/components/site-header";
import { Button } from "@/components/ui/button";

type NavItem = { href: string; label: string; icon: typeof MessageSquareTextIcon; match: (p: string) => boolean };

const NAV: NavItem[] = [
  { href: "/app", label: "Ask the copilot", icon: MessageSquareTextIcon, match: (p) => p === "/app" },
  { href: "/app/assess", label: "Assessment", icon: ClipboardCheckIcon, match: (p) => p.startsWith("/app/assess") },
];
const ADMIN_NAV: NavItem = {
  href: "/app/admin/traces",
  label: "Query traces",
  icon: ActivityIcon,
  match: (p) => p.startsWith("/app/admin"),
};

export type AppShellProps = {
  /** Account control rendered by the server (holds the sign-out action). */
  account: ReactNode;
  /** Same control, avatar-only, for the top bar on small screens. */
  accountCompact?: ReactNode;
  isAdmin?: boolean;
  /** Page-specific list under the navigation: past chats, saved assessments. */
  rail?: ReactNode;
  /** Top-bar title, kept short: the page's noun. */
  title?: string;
  /** Top-bar right-hand slot. */
  actions?: ReactNode;
  /** "reading" (52rem), "form" (48rem) or "wide" (full width) content column. */
  width?: "reading" | "form" | "wide";
  /** The chat needs its own scroll container; everything else scrolls the main area. */
  scroll?: "main" | "none";
  children: ReactNode;
};

// Content columns are centred in the main area and sized to the content, so
// a wide screen shows margin on both sides instead of a dead right gutter.
const WIDTHS = { reading: "max-w-[54rem]", form: "max-w-[50rem]", wide: "max-w-[88rem]" } as const;

function NavLinks({ isAdmin, onNavigate }: { isAdmin: boolean; onNavigate?: () => void }) {
  const pathname = usePathname() ?? "";
  const items = isAdmin ? [...NAV, ADMIN_NAV] : NAV;
  return (
    <nav aria-label="Primary" className="px-3">
      <ul className="space-y-0.5">
        {items.map(({ href, label, icon: Icon, match }) => {
          const active = match(pathname);
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={`type-meta focus-visible:ring-ring relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 transition-colors focus-visible:ring-2 focus-visible:outline-none ${
                  active
                    ? "bg-sidebar-accent text-ink ring-hairline font-medium shadow-[var(--shadow-xs)] ring-1 before:bg-accent-solid before:absolute before:top-2 before:bottom-2 before:-left-3 before:w-0.5 before:rounded-full"
                    : "text-ink-soft hover:bg-sidebar-accent/70 hover:text-ink"
                }`}
              >
                <Icon className={`size-4 ${active ? "text-accent-solid" : "text-ink-faint"}`} aria-hidden />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function SidebarBody({
  isAdmin,
  rail,
  account,
  onNavigate,
}: {
  isAdmin: boolean;
  rail?: ReactNode;
  account: ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center px-5">
        <Wordmark />
      </div>
      <div className="pt-1 pb-3">
        <NavLinks isAdmin={isAdmin} onNavigate={onNavigate} />
      </div>
      <div className="border-hairline min-h-0 flex-1 overflow-y-auto border-t">{rail}</div>
      <div className="border-hairline bg-sidebar shrink-0 border-t p-2.5">{account}</div>
    </div>
  );
}

/**
 * The signed-in application frame: one sidebar (wordmark, primary
 * navigation, a page-specific rail, the account), a slim top bar, and a
 * content area whose column is centred in the main area and sized to the
 * content (reading, form or wide). Every /app screen renders inside it so the chrome,
 * widths and spacing are the same product everywhere. Below md the sidebar
 * becomes a drawer with dialog semantics.
 */
export function AppShell({
  account,
  accountCompact,
  isAdmin = false,
  rail,
  title,
  actions,
  width = "reading",
  scroll = "main",
  children,
}: AppShellProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      trigger?.focus();
    };
  }, [open]);

  return (
    <div className="bg-paper flex h-dvh min-h-0">
      <aside
        aria-label="Navigation"
        className="border-hairline bg-sidebar hidden w-[16.5rem] shrink-0 border-r md:flex md:flex-col"
      >
        <SidebarBody isAdmin={isAdmin} rail={rail} account={account} />
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="border-hairline bg-paper/85 sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b px-4 backdrop-blur-xl md:px-8">
          <Button
            ref={triggerRef}
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setOpen(true)}
            aria-expanded={open}
            aria-controls={panelId}
            aria-label="Menu"
            className="-ml-2 md:hidden"
          >
            <MenuIcon className="size-4" aria-hidden />
          </Button>
          <div className="md:hidden">
            <Wordmark className="text-[1.05rem]" />
          </div>
          {title ? (
            <p className="type-meta text-ink hidden truncate font-medium md:block">{title}</p>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {actions}
            <div className="md:hidden">{accountCompact ?? null}</div>
          </div>
        </header>

        {scroll === "main" ? (
          <main className="min-h-0 flex-1 overflow-y-auto">
            <div className={`mx-auto w-full px-5 py-8 md:px-10 md:py-12 ${WIDTHS[width]}`}>{children}</div>
          </main>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">{children}</div>
        )}
      </div>

      {open ? (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
            className="bg-ink/40 absolute inset-0 backdrop-blur-[2px]"
          />
          <div
            id={panelId}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="border-hairline bg-sidebar absolute inset-y-0 left-0 flex w-80 max-w-[85vw] flex-col border-r [box-shadow:var(--shadow-xl)]"
          >
            <div className="absolute top-2.5 right-2.5">
              <Button
                ref={closeRef}
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setOpen(false)}
                aria-label="Close menu"
                className="rounded-full"
              >
                <XIcon className="size-4" aria-hidden />
              </Button>
            </div>
            <SidebarBody
              isAdmin={isAdmin}
              rail={rail}
              account={account}
              onNavigate={() => setOpen(false)}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
