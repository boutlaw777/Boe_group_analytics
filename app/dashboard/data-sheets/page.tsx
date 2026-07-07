import DataSheetBuilder from "@/components/DataSheetBuilder";

export default function DataSheetsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Data Sheets</h1>
        <p className="mt-1 text-sm text-slate-600">
          Pick a ticker, years, and line items, then export an audit-ready
          Excel model. Blue numbers are hardcoded and hyperlinked to their
          source; industry-specific KPI tabs are added automatically.
        </p>
      </div>
      <DataSheetBuilder />
    </div>
  );
}
