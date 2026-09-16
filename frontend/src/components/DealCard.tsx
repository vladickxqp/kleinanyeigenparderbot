/** The deal row and the hero card.
 *
 * A row is three lines: what it is, what it costs, where it came from. The
 * saving is the only coloured text; deal quality is a 5px dot in the meta
 * line. Rows live inside a grouped container, separated by hairlines, so a
 * list of finds reads as one calm block instead of a stack of cards.
 */

import { useState } from "react";
import { IconInbox, IconStar } from "./icons";

export interface DealLike {
  id: number;
  site: string;
  title: string;
  url: string;
  image_url: string | null;
  price: number | null;
  estimated_market_price: number | null;
  deal_score: number;
  deal_verdict: string;
  location: string | null;
  created_at: string;
  is_favorite?: boolean;
  is_negotiable?: boolean;
  shipping_cost?: number | null;
  discount_percent?: number | null;
}

const QUALITY: Record<string, string> = {
  steal: "var(--dh-q-steal)",
  great: "var(--dh-q-great)",
  good: "var(--dh-q-good)",
  fair: "var(--dh-q-fair)",
  overpriced: "var(--dh-q-none)",
  unknown: "var(--dh-q-none)",
};

const VERDICT: Record<string, string> = {
  steal: "Kracher",
  great: "Top-Deal",
  good: "Guter Deal",
  fair: "Fair",
  overpriced: "Teuer",
  unknown: "Unbewertet",
};

export const money = (v: number | null | undefined) =>
  v == null ? "—" : `${Math.round(v).toLocaleString("de-DE")} €`;

/** Minutes matter in this product, so age is relative, never a date. */
export function since(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "gerade eben";
  if (minutes < 60) return `vor ${minutes} Min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `vor ${hours} Std`;
  const days = Math.round(hours / 24);
  return days === 1 ? "gestern" : `vor ${days} Tagen`;
}

export function discountOf(deal: DealLike): number | null {
  if (deal.discount_percent != null && deal.discount_percent > 0) {
    return Math.round(deal.discount_percent);
  }
  if (deal.price != null && deal.estimated_market_price) {
    const pct = (1 - deal.price / deal.estimated_market_price) * 100;
    return pct > 0 ? Math.round(pct) : null;
  }
  return null;
}

/** Hotlinked marketplace photos do fail; a broken image icon must never show. */
function Photo({ src, alt }: { src: string | null; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div className="dh-thumb-empty">
        <IconInbox size={22} />
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

function Meta({ deal }: { deal: DealLike }) {
  const parts = [deal.location, since(deal.created_at)].filter(Boolean) as string[];
  if (deal.is_negotiable) parts.push("VB");
  if (deal.shipping_cost === 0) parts.push("Versand");
  return (
    <div className="dh-meta" style={{ marginTop: 6 }}>
      <span className="dh-dot" style={{ ["--q" as string]: QUALITY[deal.deal_verdict] }} />
      {VERDICT[deal.deal_verdict] ?? "—"}
      {parts.map((p) => (
        <span key={p}>
          <span className="dh-sep">·</span>
          {p}
        </span>
      ))}
    </div>
  );
}

/** One find, as a row inside a grouped list. */
export function DealRow({
  deal,
  onFavorite,
  busy = false,
}: {
  deal: DealLike;
  onFavorite?: (id: number) => void;
  busy?: boolean;
}) {
  const off = discountOf(deal);
  return (
    <div style={{ position: "relative" }}>
      <a href={deal.url} target="_blank" rel="noreferrer" className="dh-row dh-row-tap">
        <div className="dh-deal">
          <div className="dh-thumb">
            <Photo src={deal.image_url} alt={deal.title} />
          </div>

          <div style={{ minWidth: 0, flex: 1, paddingRight: onFavorite ? 30 : 0 }}>
            <div className="dh-title">{deal.title}</div>
            <div className="dh-priceline">
              <span className="dh-price dh-num">{money(deal.price)}</span>
              {deal.estimated_market_price != null && off != null && (
                <>
                  <span className="dh-was dh-num">{money(deal.estimated_market_price)}</span>
                  <span className="dh-save-text dh-num">−{off} %</span>
                </>
              )}
            </div>
            <Meta deal={deal} />
          </div>
        </div>
      </a>

      {onFavorite && (
        <button
          type="button"
          className="dh-icon-btn"
          aria-label={deal.is_favorite ? "Favorit entfernen" : "Zu Favoriten"}
          disabled={busy}
          onClick={() => onFavorite(deal.id)}
          style={{
            position: "absolute",
            top: 12,
            right: 12,
            border: 0,
            background: "none",
            color: deal.is_favorite ? "var(--dh-q-fair)" : "var(--dh-muted)",
            opacity: busy ? 0.4 : 1,
          }}
        >
          <IconStar size={18} filled={deal.is_favorite} />
        </button>
      )}
    </div>
  );
}

/** The single best current find, given the space it deserves. */
export function DealHero({ deal }: { deal: DealLike }) {
  const off = discountOf(deal);
  return (
    <a href={deal.url} target="_blank" rel="noreferrer" className="dh-hero">
      <div className="dh-hero-media">
        <Photo src={deal.image_url} alt={deal.title} />
        <div className="dh-hero-shade" />
        <span className="dh-hero-label">
          <span className="dh-dot" style={{ ["--q" as string]: QUALITY[deal.deal_verdict], margin: 0 }} />
          {VERDICT[deal.deal_verdict] ?? "Deal"}
        </span>
      </div>
      <div className="dh-hero-body">
        <div
          style={{
            fontSize: 16,
            fontWeight: 500,
            lineHeight: 1.3,
            letterSpacing: "-0.01em",
            marginBottom: 7,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {deal.title}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 9, flexWrap: "wrap" }}>
          <span className="dh-num" style={{ fontSize: 27, fontWeight: 600, letterSpacing: "-0.03em" }}>
            {money(deal.price)}
          </span>
          {deal.estimated_market_price != null && off != null && (
            <>
              <span
                className="dh-num"
                style={{
                  fontSize: 13,
                  color: "rgba(255,255,255,.62)",
                  textDecoration: "line-through",
                }}
              >
                {money(deal.estimated_market_price)}
              </span>
              <span className="dh-num" style={{ fontSize: 14, fontWeight: 600, color: "#4ade80" }}>
                −{off} %
              </span>
            </>
          )}
        </div>
        <div
          className="dh-meta"
          style={{ marginTop: 7, color: "rgba(255,255,255,.66)", fontSize: 12 }}
        >
          {deal.site}
          {deal.location ? ` · ${deal.location}` : ""} · {since(deal.created_at)}
        </div>
      </div>
    </a>
  );
}

export function DealRowSkeleton() {
  return (
    <div className="dh-row">
      <div className="dh-deal">
        <div className="dh-thumb dh-skel" style={{ boxShadow: "none" }} />
        <div style={{ flex: 1, display: "grid", gap: 9, paddingTop: 3 }}>
          <div className="dh-skel" style={{ height: 13, width: "88%" }} />
          <div className="dh-skel" style={{ height: 13, width: "52%" }} />
          <div className="dh-skel" style={{ height: 17, width: 92 }} />
          <div className="dh-skel" style={{ height: 10, width: "66%" }} />
        </div>
      </div>
    </div>
  );
}
