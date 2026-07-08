import Link from "next/link";

export default function NotFound() {
  return (
    <div className="notice">
      <p>
        That company isn&apos;t covered yet. Coverage expands regularly —
        check back soon, or browse the companies available today.
      </p>
      <p>
        <Link href="/dashboard">Browse coverage</Link>
      </p>
    </div>
  );
}
