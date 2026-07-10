import { API_BASE } from "@/lib/api";
import { PortalClient } from "@/components/PortalClient";

export const metadata = {
  title: "Developer Portal — BOE Analytics",
  description: "Create an account, manage your API keys, and track your usage",
};

export default function PortalPage() {
  return (
    <>
      <section className="hero" style={{ paddingBottom: 8 }}>
        <h1 className="hero-title" style={{ fontSize: 40 }}>Developer portal</h1>
        <p className="hero-sub">
          Create a free account, mint API keys, and watch your usage — no email
          round-trip required.
        </p>
      </section>
      <section>
        <PortalClient apiBase={API_BASE} />
      </section>
    </>
  );
}
