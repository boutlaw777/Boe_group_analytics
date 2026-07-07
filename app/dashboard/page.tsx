import FinancialsExplorer from "@/components/FinancialsExplorer";

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Company Overview</h1>
        <p className="mt-1 text-sm text-slate-600">
          Search a ticker to pull fundamentals — served from the Supabase cache
          when fresh, fetched live from SimFin otherwise. Blue values are
          hardcoded (source-linked) numbers.
        </p>
      </div>
      <FinancialsExplorer />
    </div>
  );
}
