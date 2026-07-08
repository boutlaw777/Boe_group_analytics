import { API_BASE } from "@/lib/api";
import { WatchlistView } from "@/components/WatchlistActions";

export default function WatchlistPage() {
  return (
    <>
      <h1>Watchlist</h1>
      <p className="muted">
        Companies you saved from Scout screens. Stored in this browser.
      </p>
      <WatchlistView apiBase={API_BASE} />
    </>
  );
}
