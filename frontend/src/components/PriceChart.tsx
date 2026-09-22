import type { WaPricePoint } from "../lib/webapp";

/**
 * The price of one ad over time, as plain inline SVG.
 *
 * Deliberately not a chart library: the admin dashboard's one is 400 kB and
 * lives in its own bundle precisely so the Mini App does not download it (see
 * src/App.tsx). A line, an area and two labels do not justify bringing it
 * back across that line.
 */
export function PriceChart({
  points,
  height = 120,
}: {
  points: WaPricePoint[];
  height?: number;
}) {
  if (points.length < 2) return null;

  const width = 320;
  const padY = 14;
  const prices = points.map((p) => p.price);
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  // A flat line would divide by zero and, worse, render as a line at the top.
  const span = hi - lo || Math.max(1, hi * 0.05);

  const x = (i: number) => (i / (points.length - 1)) * width;
  const y = (price: number) =>
    height - padY - ((price - lo) / span) * (height - padY * 2);

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.price).toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;

  const first = points[0].price;
  const last = points[points.length - 1].price;
  // One accent colour in this design system, and it means "money saved".
  const fell = last < first;
  const stroke = fell ? "var(--dh-accent)" : "var(--dh-muted)";

  const when = (iso: string) =>
    new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Preisverlauf von ${Math.round(first)} auf ${Math.round(last)} Euro`}
      >
        <defs>
          <linearGradient id="dh-price-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.18" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#dh-price-fill)" />
        <path
          d={line}
          fill="none"
          stroke={stroke}
          strokeWidth="1.75"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        <circle cx={x(points.length - 1)} cy={y(last)} r="3" fill={stroke} />
      </svg>
      <div
        className="dh-muted"
        style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5 }}
      >
        <span>{when(points[0].at)}</span>
        <span>{when(points[points.length - 1].at)}</span>
      </div>
    </div>
  );
}
