import type { TraceCandidate, TraceRetrieval } from "@/lib/types";

function num(v: number | null, digits: number): string {
  return v === null ? "–" : v.toFixed(digits);
}

function rank(v: number | null): string {
  // Stored 0-indexed (mirrors FusedResult); shown 1-indexed like final_rank.
  return v === null ? "–" : String(v + 1);
}

/**
 * The fused candidate list as the retriever ranked it. Rows that reached the
 * context are on paper with a grounded rule; cut rows are faint. A labelled
 * boundary row marks the context slice. Rows the actor prior pushed down
 * carry a caution chip, derived by the backend from the recorded query actor
 * and the provision's static label.
 */
export function RetrievalTable({
  candidates,
  retrieval,
}: {
  candidates: TraceCandidate[];
  retrieval: TraceRetrieval;
}) {
  const lastUsed = candidates.reduce((n, c) => (c.used_in_context ? c.final_rank : n), 0);
  const cut = candidates.length - candidates.filter((c) => c.used_in_context).length;

  return (
    <section aria-labelledby="retrieval-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="retrieval-heading" className="type-h3">
          Retrieval
        </h2>
        <p className="type-micro text-ink-soft">
          {candidates.length} candidates, {lastUsed} in context, {cut} cut.{" "}
          {retrieval.legacy
            ? "Actor prior: not recorded for this trace."
            : retrieval.query_actor
              ? `Actor prior fired for "${retrieval.query_actor}" at factor ${retrieval.factor ?? "?"}.`
              : "Actor prior did not fire (no single actor named)."}
        </p>
      </div>

      {/* The one place a horizontal scroll is allowed: the table, never the page. */}
      <div className="border-hairline mt-4 overflow-x-auto rounded-2xl border">
        <table className="w-full min-w-[56rem] border-collapse text-left">
          <thead className="bg-card">
            <tr className="type-micro text-ink-soft [&>th]:px-3 [&>th]:py-2.5 [&>th]:font-medium [&>th]:whitespace-nowrap">
              <th scope="col" className="w-12 text-right">
                #
              </th>
              <th scope="col">Provision</th>
              <th scope="col" className="text-right">
                Vector
              </th>
              <th scope="col" className="text-right">
                Lexical
              </th>
              <th scope="col" className="text-right">
                RRF
              </th>
              <th scope="col" className="text-right">
                Similarity
              </th>
              <th scope="col">Actor</th>
              <th scope="col">Flags</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <RowGroup key={c.final_rank} c={c} boundaryAfter={c.final_rank === lastUsed && cut > 0} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RowGroup({ c, boundaryAfter }: { c: TraceCandidate; boundaryAfter: boolean }) {
  const tone = c.used_in_context ? "bg-paper text-ink" : "bg-card text-ink-faint";
  return (
    <>
      <tr
        className={`border-hairline type-meta border-t align-top ${tone} [&>td]:px-3 [&>td]:py-2.5`}
        data-used={c.used_in_context ? "true" : "false"}
        data-downweighted={c.downweighted ? "true" : "false"}
      >
        <td className="relative text-right font-mono tabular-nums">
          {c.used_in_context ? (
            <span className="bg-grounded absolute inset-y-2 left-0 w-0.5 rounded-full" aria-hidden />
          ) : null}
          {c.final_rank}
        </td>
        <td className="min-w-[16rem]">
          <span className="type-mono block font-medium">{c.citation_label}</span>
          <span className="type-micro block font-mono opacity-80">{c.citation_id}</span>
          {c.chunk_preview ? (
            <details className="mt-1.5">
              <summary className="type-micro text-grounded cursor-pointer select-none hover:underline">
                Preview
              </summary>
              <p className="type-micro border-grounded/30 mt-1.5 max-w-prose border-l-2 pl-3 whitespace-pre-wrap">
                {c.chunk_preview}
              </p>
            </details>
          ) : null}
        </td>
        <td className="text-right font-mono tabular-nums">{rank(c.vector_rank)}</td>
        <td className="text-right font-mono tabular-nums">{rank(c.lexical_rank)}</td>
        <td className="text-right font-mono tabular-nums">{num(c.rrf_score, 4)}</td>
        <td className="text-right font-mono tabular-nums">{num(c.similarity, 3)}</td>
        <td className="type-micro font-mono">{c.actor ?? "–"}</td>
        <td className="whitespace-nowrap">
          <span className="flex flex-wrap gap-1.5">
            {c.used_in_context ? (
              <span className="type-micro bg-grounded/10 text-grounded rounded-full px-2 py-0.5">
                in context
              </span>
            ) : (
              <span className="type-micro bg-muted text-ink-soft rounded-full px-2 py-0.5">cut</span>
            )}
            {c.downweighted ? (
              <span className="type-micro bg-caution/[0.12] text-caution rounded-full px-2 py-0.5">
                actor prior
              </span>
            ) : null}
          </span>
        </td>
      </tr>
      {boundaryAfter ? (
        <tr aria-hidden className="border-grounded/40 border-t-2">
          <td colSpan={8} className="type-micro text-grounded bg-card px-3 py-1 text-right">
            context boundary
          </td>
        </tr>
      ) : null}
    </>
  );
}
