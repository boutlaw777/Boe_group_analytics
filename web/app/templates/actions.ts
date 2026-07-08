"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { API_BASE } from "@/lib/api";
import { CONCEPT_LABELS } from "@/lib/format";

const CONCEPTS = new Set(CONCEPT_LABELS.map(([c]) => c));

interface TemplateRow {
  type: "concept" | "formula" | "spacer";
  label?: string;
  concept?: string;
  expression?: string;
}

/** Parse the friendly line format into template config rows.
 *  "Revenue = revenue"                         -> concept row
 *  "Adj EBITDA = operating_income + stock_based_compensation" -> formula row
 *  "---"                                       -> spacer
 */
function parseRows(text: string): TemplateRow[] {
  const rows: TemplateRow[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (line === "---") {
      rows.push({ type: "spacer" });
      continue;
    }
    const eq = line.indexOf("=");
    if (eq === -1) throw new Error(`Line "${line}" needs the form: Label = expression`);
    const label = line.slice(0, eq).trim();
    const expression = line.slice(eq + 1).trim();
    if (!label || !expression) throw new Error(`Line "${line}" needs both a label and an expression`);
    if (CONCEPTS.has(expression)) {
      rows.push({ type: "concept", label, concept: expression });
    } else {
      rows.push({ type: "formula", label, expression });
    }
  }
  return rows;
}

export async function createTemplate(formData: FormData): Promise<void> {
  const name = String(formData.get("name") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const rowsText = String(formData.get("rows") ?? "");

  let error = "";
  if (!name) {
    error = "Template needs a name";
  } else {
    try {
      const rows = parseRows(rowsText);
      const res = await fetch(`${API_BASE}/templates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description, config: { rows } }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        error = body?.detail ?? `Backend rejected the template (HTTP ${res.status})`;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "Could not reach the backend";
    }
  }

  revalidatePath("/templates");
  redirect(error ? `/templates?error=${encodeURIComponent(error)}` : "/templates");
}

export async function deleteTemplate(formData: FormData): Promise<void> {
  const id = String(formData.get("id") ?? "");
  await fetch(`${API_BASE}/templates/${id}`, { method: "DELETE" }).catch(() => null);
  revalidatePath("/templates");
  redirect("/templates");
}
