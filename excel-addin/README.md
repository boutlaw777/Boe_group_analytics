# FinClone Excel Add-in (PDR Module 2)

Office.js task-pane add-in with custom functions:

- **Task pane** — pick a company, insert a formatted model at the current
  selection (blue as-reported numbers, negatives in parentheses), refresh all
  formulas.
- **`=FINCLONE.VALUE("AAPL","revenue",2024,"FY")`** — pull any value into any
  cell, straight from the backend.

## One-time setup

Office requires add-in files to be served over **HTTPS** — including the
backend API the add-in calls (mixed content is blocked). The Office dev-cert
tool handles both.

```powershell
cd "C:\Cursor Projects\PDR\excel-addin"
npm install
npm run certs      # installs a trusted localhost certificate (accept the prompt)
```

## Running (two servers)

1. Serve the add-in files over HTTPS on port 3100:

```powershell
cd "C:\Cursor Projects\PDR\excel-addin"
npm run dev
```

2. Run the backend with HTTPS on port 8443 (instead of the usual port 8000):

```powershell
cd "C:\Cursor Projects\PDR\backend"
.venv\Scripts\Activate.ps1
uvicorn finclone.api.main:app --port 8443 --ssl-keyfile "$env:USERPROFILE\.office-addin-dev-certs\localhost.key" --ssl-certfile "$env:USERPROFILE\.office-addin-dev-certs\localhost.crt"
```

Sanity check: https://localhost:3100/taskpane.html and
https://localhost:8443/health should both load in a browser without
certificate warnings.

## Sideloading the add-in

**Excel on the web (easiest):**
1. Open a workbook at office.com → **Home → Add-ins → More Add-ins**
   (or Insert → Add-ins) → **Upload My Add-in**
2. Upload `manifest.xml` from this folder
3. A **FinClone** button appears on the Home ribbon

**Excel for Windows (desktop):** sideload via a shared-folder catalog —
share this folder, then Excel → File → Options → Trust Center →
Trusted Add-in Catalogs → add the share → restart Excel →
Insert → My Add-ins → Shared Folder.

## Using it

- Click **FinClone** on the ribbon → the pane lists your ingested companies →
  select a cell → **Insert model at selection**.
- Type `=FINCLONE.VALUE("AAPL","revenue",2024)` in any cell.
- **Refresh FINCLONE formulas** re-pulls every formula from the database
  (equivalent to Ctrl+Alt+F9).

## Notes

- The backend URL is editable in the pane (default `https://localhost:8443`).
  For the custom function, edit `API_BASE` at the top of `src/functions.js`.
- Icons are referenced but not bundled; Excel shows a default icon. Add
  `src/assets/icon-{16,32,64,80}.png` to brand it.
