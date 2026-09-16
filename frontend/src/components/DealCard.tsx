/** Deal card — the one component the whole product is judged by.
 *
 * The photo comes first because that is how people scan a marketplace, the
 * price is the largest thing on the card, and colour is used for exactly one
 * message: how good this deal is. Everything else stays neutral.
 */

import { useState } from "react";

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

const RAIL: Record<string, string> = {
  steal: "var(--dh-steal)",
  great: "var(--dh-great)",
  good: "var(--dh-good)",
  fair: "var(--dh-fair)",
  overpriced: "var(--dh-overpriced)",
  unknown: "var(--dh-unknown)",
};

const VERDICT_LABEL: Record<string, string> = {
  steal: "KRACHER",
  great: "TOP-DEAL",
  good: "GUTER DEAL",
  fair: "FAIR",
  overpriced: "TEUER",
  unknown: "UNBEWERTET",
};

export const money = (v: number | null | undefined) =>
  v == null ? "—" : `${Math.round(v).toLocaleString("de-DE")} €`;

/** "vor 12 Min" reads better than a date when deals are minutes old. */
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

/** Photo with a graceful fallback: hotlinks do fail, a broken icon must not show. */
function Photo({ src, alt }: { src: string | null; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return <div className="dh-thumb-empty">kein Foto</div>;
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

export function ScoreMeter({ score, verdict }: { score: number; verdict: string }) {
  const filled = Math.max(0, Math.min(5, Math.round(score / 20)));
  return (
    <span className="dh-score" style={{ ["--rail" as string]: RAIL[verdict] ?? RAIL.unknown }}>
      <span className="dh-score-bars">
        {[0, 1, 2, 3, 4].map((i) => (
          <i key={i} className="dh-score-bar" data-on={i < filled ? 1 : 0} />
        ))}
      </span>
      <span className="dh-score-value">{score}</span>
    </span>
  );
}

/** Big card for the single best current deal — gives the screen a focal point. */
export function DealHero({ deal }: { deal: DealLike }) {
  const rail = RAIL[deal.deal_verdict] ?? RAIL.unknown;
  const off = discountOf(deal);
  return (
    <a
      href={deal.url}
      target="_blank"
      rel="noreferrer"
      className="dh-card dh-hero"
      style={{ ["--rail" as string]: rail }}
    >
      <div className="dh-hero-media">
        <Photo src={deal.image_url} alt={deal.title} />
        <div className="dh-hero-shade" />
        <span className="dh-hero-flag">{VERDICT_LABEL[deal.deal_verdict] ?? "DEAL"}</span>
      </div>
      <div className="dh-hero-body">
        <div className="dh-title" style={{ fontSize: 15, marginBottom: 4 }}>
          {deal.title}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <span className="dh-price dh-num" style={{ fontSize: 26 }}>
            {money(deal.price)}
          </span>
          {deal.estimated_market_price != null && (
            <span className="dh-price-was dh-num" style={{ color: "rgba(255,255,255,.7)" }}>
              {money(deal.estimated_market_price)}
            </span>
          )}
          {off != null && (
            <span
              className="dh-num"
              style={{
                fontFamily: "var(--dh-mono)",
                fontSize: 12,
                fontWeight: 700,
                background: rail,
                color: "#fff",
                padding: "2px 7px",
                borderRadius: 6,
              }}
            >
              −{off} %
            </span>
          )}
        </div>
        <div className="dh-meta" style={{ marginTop: 6, color: "rgba(255,255,255,.75)" }}>
          {deal.site}
          {deal.location ? ` · ${deal.location}` : ""} · {since(deal.created_at)}
        </div>
      </div>
    </a>
  );
}

export function DealCard({
  deal,
  onFavorite,
  busy = false,
}: {
  deal: DealLike;
  onFavorite?: (id: number) => void;
  busy?: boolean;
}) {
  const rail = RAIL[deal.deal_verdict] ?? RAIL.unknown;
  const off = discountOf(deal);
  return (
    <div className="dh-card" style={{ ["--rail" as string]: rail }}>
      <a href={deal.url} target="_blank" rel="noreferrer" className="dh-deal">
        <div className="dh-thumb">
          <Photo src={deal.image_url} alt={deal.title} />
          {off != null && <span className="dh-save">−{off} %</span>}
        </div>

        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="dh-title">{deal.title}</div>

          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 7,
              marginTop: 5,
              flexWrap: "wrap",
            }}
          >
            <span className="dh-price dh-num">{money(deal.price)}</span>
            {deal.is_negotiable && <span className="dh-tag">VB</span>}
            {deal.estimated_market_price != null && (
              <span className="dh-price-was dh-num">{money(deal.estimated_market_price)}</span>
            )}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginTop: 6,
              flexWrap: "wrap",
            }}
          >
            <ScoreMeter score={deal.deal_score} verdict={deal.deal_verdict} />
            {deal.shipping_cost === 0 && <span className="dh-tag">Versand</span>}
            <span className="dh-meta">
              {deal.site}
              {deal.location ? ` · ${deal.location}` : ""} · {since(deal.created_at)}
            </span>
          </div>
        </div>
      </a>

      {onFavorite && (
        <button
          type="button"
          aria-label={deal.is_favorite ? "Favorit entfernen" : "Zu Favoriten"}
          disabled={busy}
          onClick={() => onFavorite(deal.id)}
          style={{
            position: "absolute",
            top: 8,
            right: 8,
            width: 30,
            height: 30,
            display: "grid",
            placeItems: "center",
            border: "1px solid var(--dh-line-soft)",
            borderRadius: 8,
            background: "var(--dh-surface)",
            cursor: "pointer",
            opacity: busy ? 0.5 : 1,
            fontSize: 14,
          }}
        >
          {deal.is_favorite ? "★" : "☆"}
        </button>
      )}
    </div>
  );
}

export function DealSkeleton() {
  return (
    <div className="dh-card" style={{ ["--rail" as string]: "var(--dh-line)" }}>
      <div className="dh-deal">
        <div className="dh-thumb dh-skel" />
        <div style={{ flex: 1, display: "grid", gap: 8, alignContent: "start", paddingTop: 2 }}>
          <div className="dh-skel" style={{ height: 13, width: "85%" }} />
          <div className="dh-skel" style={{ height: 13, width: "55%" }} />
          <div className="dh-skel" style={{ height: 18, width: 96, marginTop: 2 }} />
          <div className="dh-skel" style={{ height: 10, width: "70%" }} />
        </div>
      </div>
    </div>
  );
}
