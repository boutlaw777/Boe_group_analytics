# BOE Analytics Excel Add-in (scaffold)

Office.js add-in providing the custom function:

```
=BOE("AAPL", "Revenue", "2023", "Q4")
```

which calls the BOE Analytics REST API (`GET /api/v1/financials`) with an API key
generated on the `/dashboard/api-keys` page.

## Status

**Scaffold only** — build this after modules 1–4 are verified working.

## Planned structure

```
excel-addin/
├── manifest.xml            # Office add-in manifest (task pane + custom functions)
├── package.json            # office-addin tooling, webpack, React
├── src/
│   ├── functions/
│   │   ├── functions.ts    # BOE custom function implementation
│   │   └── functions.json  # custom function metadata
│   └── taskpane/
│       ├── index.tsx       # React task pane entry (API key entry, ticker search)
│       └── App.tsx
└── webpack.config.js
```

## Bootstrapping (when ready)

```sh
npx yo office --projectType excel-functions --name "BOE Analytics" --ts
```

then point the custom function's fetch at `https://<deployment>/api/v1/financials`
with the `Authorization: Bearer <api_key>` header.
