import { TraceDetail } from "@/components/admin/trace-detail";

export default async function AdminTracePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <TraceDetail id={id} />;
}
