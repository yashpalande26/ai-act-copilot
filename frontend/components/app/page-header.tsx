import type { ReactNode } from "react";

/**
 * One header pattern for every signed-in page: eyebrow, a display-face
 * title, a measured lead, optional actions on the right. Spacing below is
 * fixed here so pages do not each pick their own.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="border-hairline mb-10 flex flex-col gap-5 border-b pb-8 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <p className="type-eyebrow text-ink-faint">{eyebrow}</p>
        <h1 className="type-title text-ink mt-2.5 text-balance">{title}</h1>
        {description ? (
          <p className="type-meta text-ink-soft mt-3 max-w-[40rem] text-pretty">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
