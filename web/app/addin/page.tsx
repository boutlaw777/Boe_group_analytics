export const metadata = { title: "Excel Add-in setup — BOE Analytics" };

const STEPS = [
  {
    title: "1. One-time certificates",
    body: (
      <>
        Office requires add-in files over HTTPS. In <code>excel-addin\</code> run:
        <pre>{`npm install
npm run certs   # installs a trusted localhost certificate`}</pre>
      </>
    ),
  },
  {
    title: "2. Start the two servers",
    body: (
      <>
        Serve the add-in files (port 3100), and the API over HTTPS (port 8443):
        <pre>{`# terminal 1 — in excel-addin\\
npm run dev

# terminal 2 — in backend\\
uvicorn finclone.api.main:app --port 8443 \\
  --ssl-keyfile  "$env:USERPROFILE\\.office-addin-dev-certs\\localhost.key" \\
  --ssl-certfile "$env:USERPROFILE\\.office-addin-dev-certs\\localhost.crt"`}</pre>
        Sanity check: <code>https://localhost:3100/taskpane.html</code> and{" "}
        <code>https://localhost:8443/health</code> should load without warnings.
      </>
    ),
  },
  {
    title: "3. Load it into Excel",
    body: (
      <>
        <b>Excel on the web (easiest):</b> open a workbook at office.com →{" "}
        <i>Home → Add-ins → More Add-ins → Upload My Add-in</i> → upload{" "}
        <code>excel-addin\manifest.xml</code>. A <b>BOE Analytics</b> button
        appears on the Home ribbon.
        <br />
        <br />
        <b>Excel for Windows:</b> share the <code>excel-addin\</code> folder,
        add it under <i>File → Options → Trust Center → Trusted Add-in
        Catalogs</i>, restart Excel, then <i>Insert → My Add-ins → Shared
        Folder</i>.
      </>
    ),
  },
  {
    title: "4. Use it",
    body: (
      <>
        <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
          <li>
            Click <b>BOE Analytics</b> on the ribbon → pick a company → select
            a cell → <b>Insert model at selection</b>: a formatted model lands
            at your cursor (blue as-reported numbers, negatives in
            parentheses).
          </li>
          <li>
            Type <code>=BOE.VALUE(&quot;AAPL&quot;,&quot;revenue&quot;,2024,&quot;FY&quot;)</code>{" "}
            in any cell to pull a single value straight from the database.
          </li>
          <li>
            <b>Refresh BOE formulas</b> re-pulls every formula in the workbook
            with the latest data.
          </li>
        </ul>
      </>
    ),
  },
];

export default function AddinSetupPage() {
  return (
    <>
      <h1>Excel Add-in setup</h1>
      <p className="muted" style={{ maxWidth: 720 }}>
        The add-in is an Office.js task pane plus a custom function. It runs
        against your local BOE Analytics backend — data never leaves your
        machine. Setup takes about five minutes, once.
      </p>

      {STEPS.map((s) => (
        <div key={s.title} className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>{s.title}</h3>
          <div className="muted" style={{ lineHeight: 1.6 }}>{s.body}</div>
        </div>
      ))}

      <p className="muted">
        The backend URL is editable in the task pane (default{" "}
        <code>https://localhost:8443</code>). Concept names accepted by{" "}
        <code>=BOE.VALUE()</code> are the same canonical concepts the API
        serves — <code>revenue</code>, <code>net_income</code>,{" "}
        <code>eps_diluted</code>, <code>operating_cash_flow</code>, and so on.
      </p>
    </>
  );
}
