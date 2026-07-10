import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "BOE Analytics — Speed to Conviction",
  description: "Auditable SEC financial data and Excel models",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // suppressHydrationWarning on <html>/<body>: browser extensions inject
  // attributes (data-theme, cz-shortcut-listen, ...) before React hydrates,
  // triggering false-positive hydration warnings in dev. Only attribute
  // mismatches on these two elements are suppressed.
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <div className="topbar">
          <Link href="/" className="brand">BOE Analytics</Link>
          <Link href="/dashboard" style={{ color: "#cfe0ef" }}>Dashboard</Link>
          <Link href="/scout" style={{ color: "#cfe0ef" }}>Scout</Link>
          <Link href="/watchlist" style={{ color: "#cfe0ef" }}>Watchlist</Link>
          <Link href="/templates" style={{ color: "#cfe0ef" }}>Templates</Link>
          <Link href="/developers" style={{ color: "#cfe0ef" }}>Developers</Link>
          <span className="tag">Speed to Conviction</span>
        </div>
        <main>{children}</main>
        <footer className="site-footer">
          <div className="cols">
            <div>
              <h4>BOE Analytics</h4>
              <p style={{ margin: "0 0 4px", fontStyle: "italic", color: "#8aa5bd" }}>
                Speed to Conviction
              </p>
              <p style={{ maxWidth: 300, lineHeight: 1.5 }}>
                SEC fundamentals with a paper trail — extracted, validated, and
                linked to the filings they came from.
              </p>
            </div>
            <div>
              <h4>Product</h4>
              <Link href="/dashboard">Dashboard</Link>
              <Link href="/scout">Scout</Link>
              <Link href="/templates">Templates</Link>
            </div>
            <div>
              <h4>Developers</h4>
              <Link href="/developers">API documentation</Link>
              <Link href="/developers/portal">Developer portal — API keys</Link>
              <a href="https://www.sec.gov/edgar" target="_blank" rel="noreferrer">SEC EDGAR</a>
            </div>
            <div>
              <h4>Company</h4>
              <a href="mailto:mohsin@boegroup.com">Contact</a>
            </div>
          </div>
          <div className="copyright">
            © {new Date().getFullYear()} BOE Analytics. Data sourced from SEC
            EDGAR; validation via independent reference data. Not investment
            advice.
          </div>
        </footer>
      </body>
    </html>
  );
}
