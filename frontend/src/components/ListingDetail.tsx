import { useEffect, useState } from "react";
import { PriceChart } from "./PriceChart";
import { IconAlert, IconCancel, IconStar } from "./icons";
import {
  WebAppError,
  eur,
  webapp,
  type WaComparison,
  type WaListingDetail,
} from "../lib/webapp";

/**
 * One find, opened up.
 *
 * The deal card answers "is this cheap?" with a single number and never shows
 * what that number was measured against. This does: the full description (the
 * defect is usually in there, not in the title), this ad's own price over
 * time, and what comparable ads of the SAME kind are asking — or, better,
 * actually sold for.
 */
export function ListingDetail({
  id,
  onClose,
  onChanged,
}: {
  id: number;
  onClose: () => void;
  /** Called after the sheet changed the find, so the list behind it reloads. */
  onChanged?: () => void;
}) {
  const [data, setData] = useState<WaListingDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    webapp
      .listingDetail(id)
      .then((d) => alive && setData(d))
      .catch((e: unknown) =>
        alive && setError(e instanceof WebAppError ? e.message : "Fehler beim Laden"),
      );
    return () => {
      alive = false;
    };
  }, [id]);

  // Escape closes the sheet — on a phone that is the back gesture, on a
  // desktop browser it is the only way out without reaching for the mouse.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="dh-sheet" role="dialog" aria-modal="true" aria-label="Angebot">
      <div className="dh-sheet-bar">
        <button
          type="button"
          className="dh-icon-btn"
          aria-label="Schließen"
          onClick={onClose}
          style={{ border: 0, background: "none", color: "var(--dh-muted)" }}
        >
          <IconCancel size={18} />
        </button>
        <span style={{ fontSize: 15, fontWeight: 500 }}>Angebot</span>
      </div>

      {error && (
        <div className="dh-group" style={{ margin: 12 }}>
          <div className="dh-row">{error}</div>
        </div>
      )}
      {!data && !error && (
        <div className="dh-muted" style={{ padding: 20, fontSize: 13.5 }}>
          Lädt…
        </div>
      )}
      {data && <Body data={data} onClose={onClose} onChanged={onChanged} />}
    </div>
  );
}

function Body({
  data,
  onClose,
  onChanged,
}: {
  data: WaListingDetail;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const { listing } = data;
  const [blocked, setBlocked] = useState(data.seller_blocked);
  const [blocking, setBlocking] = useState(false);
  // The two switches the chat card has had all along. Starred stays in the
  // sheet; hidden closes it, because there is nothing left to look at.
  const [starred, setStarred] = useState(listing.is_favorite);
  const [busy, setBusy] = useState(false);

  async function blockSeller() {
    if (!window.confirm(`Keine Angebote von „${data.seller_name}" mehr anzeigen?`)) return;
    setBlocking(true);
    try {
      await webapp.blockSeller(listing.id);
      setBlocked(true);
    } finally {
      setBlocking(false);
    }
  }

  async function toggleStar() {
    setBusy(true);
    try {
      const res = await webapp.favoriteListing(listing.id);
      setStarred(res.is_favorite);
      onChanged?.();
    } finally {
      setBusy(false);
    }
  }

  async function hide() {
    if (!window.confirm("Dieses Angebot dauerhaft ausblenden?")) return;
    setBusy(true);
    try {
      await webapp.ignoreListing(listing.id);
      onChanged?.();
      onClose();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: 12 }}>
      {listing.image_url && (
        <img
          src={listing.image_url}
          alt={listing.title}
          style={{ width: "100%", borderRadius: 12, objectFit: "cover", maxHeight: 240 }}
        />
      )}

      <div className="dh-group">
        <div className="dh-row">
          <div style={{ fontSize: 15.5, fontWeight: 500, lineHeight: 1.35 }}>
            {listing.title}
          </div>
          <div className="dh-priceline" style={{ marginTop: 8 }}>
            <span className="dh-price dh-num">{eur(listing.price)}</span>
            {data.price_fell != null && (
              <span className="dh-save-text dh-num">−{eur(data.price_fell)}</span>
            )}
          </div>
          <div className="dh-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
            {listing.site_label}
            {listing.location ? ` · ${listing.location}` : ""}
          </div>
        </div>
      </div>

      {/* The title rarely says it; the description almost always does. */}
      {data.is_defective && (
        <div className="dh-group" style={{ overflow: "hidden" }}>
          <div className="dh-defect">
            <IconAlert size={16} />
            <span>
              Defekt laut Anzeigentext
              {data.defect_markers.length > 0 && <> — „{data.defect_markers.join("“, „")}“</>}
            </span>
          </div>
        </div>
      )}
      {data.is_part && (
        <div className="dh-group">
          <div className="dh-row dh-muted" style={{ fontSize: 13 }}>
            Das ist ein Ersatzteil, kein komplettes Gerät — verglichen wird nur mit
            anderen Ersatzteilen.
          </div>
        </div>
      )}

      {data.history.length > 1 && (
        <div className="dh-group">
          <div className="dh-row">
            <div className="dh-label">Preisverlauf</div>
            <div style={{ marginTop: 8 }}>
              <PriceChart points={data.history} />
            </div>
          </div>
        </div>
      )}

      <Reference data={data} />

      {data.description && (
        <div className="dh-group">
          <div className="dh-row">
            <div className="dh-label">Beschreibung</div>
            <div style={{ fontSize: 13.5, lineHeight: 1.5, marginTop: 6, whiteSpace: "pre-wrap" }}>
              {data.description}
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          className="dh-btn dh-btn-quiet"
          style={{ flex: 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6 }}
          disabled={busy}
          onClick={toggleStar}
          aria-pressed={starred}
        >
          <IconStar size={15} />
          {starred ? "Gemerkt" : "Merken"}
        </button>
        <button
          type="button"
          className="dh-btn dh-btn-quiet"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={hide}
        >
          Ausblenden
        </button>
      </div>

      {/* Offered only where the marketplace actually names a seller: a block
          that silently matches nothing is worse than no button. */}
      {data.can_block_seller && (
        <button
          type="button"
          className="dh-btn dh-btn-quiet"
          disabled={blocked || blocking}
          onClick={blockSeller}
        >
          {blocked
            ? `„${data.seller_name}" ist gesperrt`
            : `Keine Angebote von „${data.seller_name}" mehr`}
        </button>
      )}

      <a
        className="dh-btn"
        href={listing.url}
        target="_blank"
        rel="noreferrer"
        style={{ textAlign: "center", textDecoration: "none" }}
      >
        Beim Anbieter öffnen
      </a>
    </div>
  );
}

/** What comparable ads cost — sold prices when there are enough, else asking. */
function Reference({ data }: { data: WaListingDetail }) {
  const sold = data.sold;
  const asking = data.asking;
  const lead: WaComparison | null =
    data.reference === "sold" ? sold : data.reference === "asking" ? asking : null;

  if (!lead) {
    return (
      <div className="dh-group">
        <div className="dh-row dh-muted" style={{ fontSize: 13 }}>
          Noch zu wenige vergleichbare Angebote für eine belastbare Einschätzung
          {data.compared_with > 0 && <> (bisher {data.compared_with})</>}. Je länger
          die Suche läuft, desto genauer wird sie.
        </div>
      </div>
    );
  }

  const isSold = data.reference === "sold";
  return (
    <div className="dh-group">
      <div className="dh-row">
        <div className="dh-label">
          {isSold ? "Tatsächlich verkauft" : "Vergleichbare Angebote"}
        </div>
        <div className="dh-figure dh-num" style={{ marginTop: 5 }}>
          {eur(lead.median)}
        </div>
        <div className="dh-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
          Median aus {lead.count}{" "}
          {isSold ? "verkauften" : "laufenden"} Angeboten derselben Art
          {lead.minimum != null && lead.maximum != null && (
            <> · {eur(lead.minimum)}–{eur(lead.maximum)}</>
          )}
        </div>
        {lead.discount_percent != null && (
          <div
            className="dh-num"
            style={{
              marginTop: 8,
              fontSize: 13.5,
              color:
                lead.discount_percent > 0 ? "var(--dh-accent)" : "var(--dh-muted)",
            }}
          >
            {lead.discount_percent > 0
              ? `${lead.discount_percent} % darunter`
              : `${Math.abs(lead.discount_percent)} % darüber`}
          </div>
        )}
      </div>
      {isSold && asking?.usable && (
        <div className="dh-row dh-muted" style={{ fontSize: 12.5 }}>
          Verkäufer verlangen aktuell im Mittel {eur(asking.median)} — bezahlt wurde
          weniger. Deshalb wird gegen die verkauften Preise gerechnet.
        </div>
      )}
    </div>
  );
}
