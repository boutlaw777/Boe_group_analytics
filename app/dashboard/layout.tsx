import Link from "next/link";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/data-sheets", label: "Data Sheets" },
  { href: "/dashboard/scout", label: "Scout" },
  { href: "/dashboard/mcp", label: "MCP Templates" },
  { href: "/dashboard/api-keys", label: "API Keys" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-white p-4">
        <Link href="/" className="mb-6 block text-xl font-bold text-blue-700">
          BOE Analytics
        </Link>
        <nav className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="block rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-blue-50 hover:text-blue-700"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-8">{children}</main>
    </div>
  );
}
