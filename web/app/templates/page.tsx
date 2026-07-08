import { getJSON } from "@/lib/api";
import { CONCEPT_LABELS } from "@/lib/format";
import { createTemplate, deleteTemplate } from "./actions";

interface Template {
  id: number;
  name: string;
  description: string;
  config: { rows: { type: string; label?: string; concept?: string; expression?: string }[] };
}

const EXAMPLE = `Stock-Based Comp = stock_based_compensation
Revenue = revenue
Operating Income = operating_income
---
Adjusted EBIT = operating_income + stock_based_compensation`;

export default async function TemplatesPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const templates = await getJSON<Template[]>("/templates");

  return (
    <>
      <h1>Model Templates</h1>
      <p className="muted">
        Define your own row order and custom calculated lines. Templates apply
        to any company&apos;s Data Sheet download.
      </p>

      {error && <div className="notice">⚠ {decodeURIComponent(error)}</div>}

      <h2>Create a template</h2>
      <form action={createTemplate} className="card">
        <p>
          <input name="name" placeholder="Template name, e.g. My Adjusted Model"
                 style={{ width: "60%", padding: "8px 12px", fontFamily: "inherit" }} />
        </p>
        <p>
          <input name="description" placeholder="Description (optional)"
                 style={{ width: "60%", padding: "8px 12px", fontFamily: "inherit" }} />
        </p>
        <p className="muted">
          One row per line: <code>Label = concept_or_formula</code>. Use{" "}
          <code>---</code> for a blank spacer row. Formulas combine concepts
          with + and −.
        </p>
        <p>
          <textarea name="rows" rows={8} defaultValue={EXAMPLE}
                    style={{ width: "100%", padding: "10px", fontFamily: "Consolas, monospace", fontSize: 13 }} />
        </p>
        <button className="btn" type="submit">Save template</button>
      </form>

      <h2>Saved templates</h2>
      {!templates || templates.length === 0 ? (
        <p className="muted">No templates yet.</p>
      ) : (
        templates.map((t) => (
          <div key={t.id} className="card">
            <strong>{t.name}</strong>
            {t.description && <span className="muted"> — {t.description}</span>}
            <ul className="muted" style={{ fontSize: 13 }}>
              {t.config.rows.map((r, i) => (
                <li key={i}>
                  {r.type === "spacer"
                    ? "— spacer —"
                    : r.type === "concept"
                      ? `${r.label} (${r.concept})`
                      : `${r.label} = ${r.expression}  [formula]`}
                </li>
              ))}
            </ul>
            <form action={deleteTemplate} style={{ display: "inline" }}>
              <input type="hidden" name="id" value={t.id} />
              <button className="btn secondary" type="submit">Delete</button>
            </form>
          </div>
        ))
      )}

      <h2>Available concepts</h2>
      <p className="muted" style={{ fontFamily: "Consolas, monospace", fontSize: 13 }}>
        {CONCEPT_LABELS.map(([c]) => c).join(" · ")}
      </p>
    </>
  );
}
