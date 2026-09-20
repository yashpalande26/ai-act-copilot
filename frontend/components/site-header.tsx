import Link from "next/link";
import { ScaleIcon } from "lucide-react";

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <Link
      href="/"
      className="focus-visible:ring-ring group flex items-center gap-2.5 rounded-md focus-visible:ring-2 focus-visible:outline-none"
    >
      <span className="bg-brand-solid text-brand-on flex size-8 items-center justify-center rounded-[0.55rem]">
        <ScaleIcon className="size-[15px]" aria-hidden />
      </span>
      {/* The wordmark carries the display face: the one place the editorial
          voice appears in the app chrome, so the brand reads institutional
          even on screens that are otherwise pure UI. */}
      <span
        className={`font-display text-ink text-[1.2rem] leading-none tracking-[-0.01em] ${className}`}
      >
        AI Act Copilot
      </span>
    </Link>
  );
}

export function SiteHeader({
  children,
  width = "wide",
}: {
  children?: React.ReactNode;
  /** "narrow" aligns the chrome to the app's 3xl reading column, so the
   *  wordmark sits above the conversation rather than floating far left. */
  width?: "wide" | "narrow";
}) {
  return (
    <header className="border-hairline bg-paper/85 sticky top-0 z-40 border-b backdrop-blur-xl">
      <div
        className={`mx-auto flex h-16 w-full items-center justify-between px-6 ${
          width === "narrow" ? "max-w-3xl" : "max-w-6xl"
        }`}
      >
        <Wordmark />
        <div className="flex items-center gap-2">{children}</div>
      </div>
    </header>
  );
}
