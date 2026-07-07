import ScoutSearch from "@/components/ScoutSearch";

export default function ScoutPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Scout — AI Search &amp; Screener</h1>
        <p className="mt-1 text-sm text-slate-600">
          Describe what you&apos;re looking for in plain English. Claude parses
          it into a structured filter and screens the cached company universe.
        </p>
      </div>
      <ScoutSearch />
    </div>
  );
}
