/**
 * Excel data-sheet generation with exceljs.
 *
 * Conventions (Daloopa-style):
 *  - Hardcoded (source) numbers: BLUE font, hyperlinked to their source_url.
 *  - Formula cells (custom template formulas): BLACK font, real Excel formulas.
 *  - Negative numbers rendered in parentheses via number format.
 */
import ExcelJS from "exceljs";
import type { CompanyRow, FinancialRow } from "./financials";
import { getIndustryTabs } from "./industryKpis";

const BLUE_FONT = { color: { argb: "FF0000FF" } };
const BLACK_FONT = { color: { argb: "FF000000" } };

export type Units = "raw" | "millions" | "billions";

const UNIT_CONFIG: Record<Units, { divisor: number; decimals: number; label: string | null }> = {
  raw: { divisor: 1, decimals: 0, label: null },
  millions: { divisor: 1e6, decimals: 1, label: "USD millions" },
  billions: { divisor: 1e9, decimals: 2, label: "USD billions" },
};

/** Decimals for per-share / ratio items that are never unit-scaled. */
const UNSCALED_DECIMALS = 2;

// Excel re-groups the `,` separator to the viewer's OS digit grouping (e.g.
// lakh/crore 1,33,230 on en-IN Windows), and locale tags like [$-en-US] or
// [$-409] do NOT override group sizes (verified against desktop Excel).
// The only locale-proof way to force Western 3-digit grouping is literal
// escaped commas — which must match the value's magnitude exactly, so the
// format is computed per cell.
function fixedGroupFmt(value: number, decimals: number): string {
  const scale = 10 ** decimals;
  const rounded = Math.round(Math.abs(value) * scale) / scale;
  const intDigits = Math.max(1, Math.trunc(rounded).toString().length);
  const groups = Math.ceil(intDigits / 3) - 1;
  const int =
    groups === 0 ? "0" : "#" + "\\,###".repeat(groups - 1) + "\\,##0";
  const pattern = decimals > 0 ? `${int}.${"0".repeat(decimals)}` : int;
  return `${pattern};(${pattern})`;
}

// Formula results aren't known at build time, so per-value formats aren't
// possible — bucket positive magnitudes with conditions instead. Negatives
// fall into the first section and render with a minus sign, ungrouped
// (conditional formats don't leave enough sections for parens).
function formulaFmt(decimals: number): string {
  const d = decimals > 0 ? "." + "0".repeat(decimals) : "";
  return `[<1000]0${d};[<1000000]#\\,##0${d};#\\,###\\,##0${d}`;
}

/**
 * Line items that must never be unit-scaled: per-share amounts, margins,
 * ratios and other already-normalized figures.
 */
const NON_SCALABLE = /per share|margin|ratio|return on|turnover|yield|payout|coverage|%/i;

function isScalable(lineItem: string): boolean {
  return !NON_SCALABLE.test(lineItem);
}

export interface FormulaToken {
  type: "item" | "op" | "number";
  value: string;
}

export interface CustomFormula {
  name: string;
  tokens: FormulaToken[];
}

export interface TemplateConfig {
  name: string;
  rowMapping: string[]; // ordered line-item names; empty = natural order
  customFormulas: CustomFormula[];
}

export interface DataSheetInput {
  company: CompanyRow;
  period: string;
  years: number[]; // ascending
  lineItems: string[]; // which items to include, in order
  rows: FinancialRow[]; // all cached rows across the selected years
  template?: TemplateConfig | null;
  /** Display units for monetary values. Defaults to "raw". */
  units?: Units;
}

function columnLetter(index: number): string {
  // 1 -> A, 2 -> B ... (years never exceed a handful of columns)
  let letters = "";
  let n = index;
  while (n > 0) {
    const rem = (n - 1) % 26;
    letters = String.fromCharCode(65 + rem) + letters;
    n = Math.floor((n - 1) / 26);
  }
  return letters;
}

/** Write a hardcoded (blue, hyperlinked) value cell, scaled per `units`. */
function writeHardcodedCell(
  cell: ExcelJS.Cell,
  lineItem: string,
  rawValue: number | null,
  sourceUrl: string | null,
  units: Units
) {
  if (rawValue === null) {
    cell.value = null;
    return;
  }
  const scalable = isScalable(lineItem);
  const value = scalable ? rawValue / UNIT_CONFIG[units].divisor : rawValue;
  if (sourceUrl) {
    // HYPERLINK formula keeps the cell numeric (so the parentheses number
    // format applies) while making the blue value clickable.
    const safeUrl = sourceUrl.replace(/"/g, '""');
    cell.value = { formula: `HYPERLINK("${safeUrl}",${value})`, result: value };
  } else {
    cell.value = value;
  }
  cell.font = { ...BLUE_FONT };
  cell.numFmt = fixedGroupFmt(
    value,
    scalable ? UNIT_CONFIG[units].decimals : UNSCALED_DECIMALS
  );
}

export async function buildDataSheetWorkbook(
  input: DataSheetInput
): Promise<ExcelJS.Buffer> {
  const { company, period, years, template, rows } = input;
  const units: Units = input.units ?? "raw";
  const unitLabel = UNIT_CONFIG[units].label;

  // value lookup: lineItem -> year -> row
  const byItem = new Map<string, Map<number, FinancialRow>>();
  for (const row of rows) {
    if (!byItem.has(row.line_item)) byItem.set(row.line_item, new Map());
    byItem.get(row.line_item)!.set(row.fiscal_year, row);
  }

  // Apply template row order when provided: mapped items first (in template
  // order), then any selected items the template doesn't mention.
  let orderedItems = input.lineItems;
  if (template && template.rowMapping.length > 0) {
    const selected = new Set(input.lineItems);
    const mapped = template.rowMapping.filter((li) => selected.has(li));
    const rest = input.lineItems.filter((li) => !template.rowMapping.includes(li));
    orderedItems = [...mapped, ...rest];
  }

  const workbook = new ExcelJS.Workbook();
  workbook.creator = "BOE Analytics";

  // ---------------------------------------------------------------- main tab
  const sheet = workbook.addWorksheet("Data Sheet");
  sheet.getColumn(1).width = 42;
  years.forEach((_, i) => (sheet.getColumn(i + 2).width = 15));

  sheet.getCell("A1").value = company.name;
  sheet.getCell("A1").font = { bold: true, size: 14 };
  sheet.getCell("A2").value = [
    company.ticker,
    company.sector,
    company.industry,
    `${period} data`,
    unitLabel
      ? `Values in ${unitLabel} (per-share & ratio items unscaled)`
      : null,
  ]
    .filter(Boolean)
    .join("  ·  ");
  sheet.getCell("A2").font = { color: { argb: "FF64748B" } };

  const headerRowIdx = 4;
  const headerRow = sheet.getRow(headerRowIdx);
  headerRow.getCell(1).value = "Line Item";
  years.forEach((year, i) => {
    headerRow.getCell(i + 2).value = period === "FY" ? `FY${year}` : `${period} ${year}`;
  });
  headerRow.font = { bold: true };
  headerRow.border = { bottom: { style: "thin" } };

  const rowIndexByItem = new Map<string, number>();
  let rowIdx = headerRowIdx + 1;

  for (const item of orderedItems) {
    const row = sheet.getRow(rowIdx);
    row.getCell(1).value = item;
    years.forEach((year, i) => {
      const dataRow = byItem.get(item)?.get(year);
      writeHardcodedCell(
        row.getCell(i + 2),
        item,
        dataRow?.value ?? null,
        dataRow?.source_url ?? null,
        units
      );
    });
    rowIndexByItem.set(item, rowIdx);
    rowIdx++;
  }

  // ------------------------------------------------- custom formula rows
  if (template && template.customFormulas.length > 0) {
    rowIdx++; // blank spacer
    const sectionRow = sheet.getRow(rowIdx++);
    sectionRow.getCell(1).value = `Custom Formulas (${template.name})`;
    sectionRow.font = { bold: true, italic: true };

    for (const cf of template.customFormulas) {
      const row = sheet.getRow(rowIdx);
      row.getCell(1).value = cf.name;

      years.forEach((_, i) => {
        const col = columnLetter(i + 2);
        let valid = cf.tokens.length > 0;
        const expr = cf.tokens
          .map((tok) => {
            if (tok.type === "op") return tok.value;
            if (tok.type === "number") return tok.value;
            const itemRow = rowIndexByItem.get(tok.value);
            if (!itemRow) {
              valid = false;
              return "";
            }
            return `${col}${itemRow}`;
          })
          .join("");

        const cell = row.getCell(i + 2);
        if (valid) {
          cell.value = { formula: expr } as ExcelJS.CellFormulaValue;
          cell.font = { ...BLACK_FONT }; // formulas are black
          cell.numFmt = formulaFmt(UNIT_CONFIG[units].decimals);
        } else {
          cell.value = "n/a";
          cell.font = { color: { argb: "FF94A3B8" }, italic: true };
        }
      });

      rowIndexByItem.set(cf.name, rowIdx);
      rowIdx++;
    }
  }

  // ------------------------------------------------- industry KPI tabs
  for (const tab of getIndustryTabs(company.sector, company.industry)) {
    const kpiSheet = workbook.addWorksheet(tab.tabName);
    kpiSheet.getColumn(1).width = 36;
    kpiSheet.getColumn(2).width = 60;
    years.forEach((_, i) => (kpiSheet.getColumn(i + 3).width = 15));

    kpiSheet.getCell("A1").value = `${company.name} — ${tab.tabName}`;
    kpiSheet.getCell("A1").font = { bold: true, size: 13 };

    const kpiHeader = kpiSheet.getRow(3);
    kpiHeader.getCell(1).value = "KPI";
    kpiHeader.getCell(2).value = "Notes";
    years.forEach((year, i) => {
      kpiHeader.getCell(i + 3).value = period === "FY" ? `FY${year}` : `${period} ${year}`;
    });
    kpiHeader.font = { bold: true };
    kpiHeader.border = { bottom: { style: "thin" } };

    let kpiRowIdx = 4;
    for (const kpi of tab.kpis) {
      const row = kpiSheet.getRow(kpiRowIdx++);
      row.getCell(1).value = kpi.name;
      row.getCell(2).value = kpi.note;
      row.getCell(2).font = { color: { argb: "FF64748B" } };

      // Pull in related reported line items underneath, when we have them.
      for (const related of kpi.relatedLineItems ?? []) {
        const itemYears = byItem.get(related);
        if (!itemYears) continue;
        const relRow = kpiSheet.getRow(kpiRowIdx++);
        relRow.getCell(1).value = `    ${related}`;
        years.forEach((year, i) => {
          const dataRow = itemYears.get(year);
          writeHardcodedCell(
            relRow.getCell(i + 3),
            related,
            dataRow?.value ?? null,
            dataRow?.source_url ?? null,
            units
          );
        });
      }
    }
  }

  return workbook.xlsx.writeBuffer();
}
