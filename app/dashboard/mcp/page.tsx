import TemplateBuilder from "@/components/TemplateBuilder";

export default function McpPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">
          MCP — Model Customization Platform
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Build reusable templates: reorder statement line items and define
          custom formulas (e.g. Adjusted EBITDA = EBITDA + Restructuring
          Costs). Templates apply during Data Sheet Excel generation — custom
          formulas render as real Excel formulas in black font.
        </p>
      </div>
      <TemplateBuilder />
    </div>
  );
}
