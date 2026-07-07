import ApiKeyManager from "@/components/ApiKeyManager";

export default function ApiKeysPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Developer API Keys</h1>
        <p className="mt-1 text-sm text-slate-600">
          Generate and revoke keys for the REST API under /api/v1. Rate limits
          apply per key by tier.
        </p>
      </div>
      <ApiKeyManager />
    </div>
  );
}
