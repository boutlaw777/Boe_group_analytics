import Link from "next/link";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-4xl font-bold">BOE Analytics</h1>
      <p className="max-w-md text-center text-slate-600">
        Fundamental financial data, AI screening, and audit-ready Excel exports
        — powered by SimFin.
      </p>
      <Link
        href="/dashboard"
        className="rounded-lg bg-blue-600 px-5 py-2.5 font-medium text-white hover:bg-blue-700"
      >
        Open Dashboard
      </Link>
    </main>
  );
}
