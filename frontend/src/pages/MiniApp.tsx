import { useEffect, useState, type ReactNode } from "react";
import { VerdictBadge } from "../components/VerdictBadge";
import {
  SDK_URL,
  WebAppError,
  dateDE,
  eur,
  tg,
  webapp,
  type Me,
  type WaFlips,
  type WaListing,
  type WaPayment,
  type WaRule,
} from "../lib/webapp";

type Tab = "deals" | "rules" | "flips" | "premium";

const TABS: { id: Tab; label: string }[] = [
  { id: "deals", label: "🔥 Deals" },
  { id: "rules", label: "📋 Suchen" },
  { id: "flips", label: "📦 Flips" },
  { id: "premium", label: "💎 Premium" },
];

// Telegram injects --tg-theme-* CSS variables on the root once the SDK runs;
// the fallbacks keep the page readable in a normal browser.
const BG = "bg-[var(--tg-theme-bg-color,#f8fafc)] text-[var(--tg-theme-text-color,#0f172a)]";
const CARD = "rounded-2xl p-4 bg-[var(--tg-theme-secondary-bg-color,#ffffff)] shadow-sm";
const HINT = "text-[var(--tg-theme-hint-color,#64748b)] text-sm";
const BTN = "rounded-xl px-4 py-2 text-sm font-medium bg-[var(--tg-theme-button-color,#2563eb)] text-[var(--tg-theme-button-text-color,#ffffff)]";

function useTelegramSdk(): boolean {
  const [ready, setReady] = useState(!!tg());
  useEffect(() => {
    if (tg()) {
      tg()?.ready();
      tg()?.expand();
      setReady(true);
      return;
    }
    const s = document.createElement("script");
    s.src = SDK_URL;
    s.async = true;
    s.onload = () => {
      tg()?.ready();
      tg()?.expand();
      setReady(true);
    };
    s.onerror = () => setReady(true); // still render (outside Telegram)
    document.head.appendChild(s);
  }, []);
  return ready;
}

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((e: unknown) => {
        const msg = e instanceof WebAppError ? e.message : "Fehler beim Laden";
        if (alive) setState({ data: null, error: msg, loading: false });
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </div>
  );
}

function Notice({ text }: { text: string }) {
  return <div className={`${CARD} ${HINT}`}>{text}</div>;
}

// --- Tabs ---------------------------------------------------------------------------
function DealsTab() {
  const [favs, setFavs] = useState(false);
  const { data, error, loading } = useLoad<WaListing[]>(() => webapp.listings(favs), [favs]);
  return (
    <Section title={favs ? "⭐ Favoriten" : "🔥 Deine letzten Deals"}>
      <div className="flex gap-2">
        <button className={favs ? `${BTN} opacity-60` : BTN} onClick={() => setFavs(false)}>
          Alle
        </button>
        <button className={favs ? BTN : `${BTN} opacity-60`} onClick={() => setFavs(true)}>
          ⭐ Favoriten
        </button>
      </div>
      {loading && <Notice text="Lädt…" />}
      {error && <Notice text={`⚠️ ${error}`} />}
      {data && data.length === 0 && <Notice text="Noch keine Deals — leg im Bot eine Suche an." />}
      {data?.map((l) => (
        <a key={l.id} href={l.url} target="_blank" rel="noreferrer" className={`${CARD} block`}>
          <div className="flex gap-3">
            {l.image_url && (
              <img src={l.image_url} alt="" className="h-20 w-20 flex-none rounded-xl object-cover" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <div className="line-clamp-2 font-medium">{l.title}</div>
                <VerdictBadge verdict={l.deal_verdict} />
              </div>
              <div className="mt-1 text-lg font-semibold">{eur(l.price)}</div>
              <div className={HINT}>
                Score {l.deal_score}
                {l.estimated_market_price ? ` · Markt ~${eur(l.estimated_market_price)}` : ""}
                {l.location ? ` · 📍 ${l.location}` : ""} · {dateDE(l.created_at)}
              </div>
            </div>
          </div>
        </a>
      ))}
    </Section>
  );
}

function RulesTab() {
  const [version, setVersion] = useState(0);
  const { data, error, loading } = useLoad<WaRule[]>(() => webapp.rules(), [version]);
  const [busy, setBusy] = useState<number | null>(null);

  async function toggle(id: number) {
    setBusy(id);
    try {
      await webapp.toggleRule(id);
      tg()?.HapticFeedback?.impactOccurred("light");
      setVersion((v) => v + 1);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section title="📋 Meine Suchen">
      {loading && <Notice text="Lädt…" />}
      {error && <Notice text={`⚠️ ${error}`} />}
      {data && data.length === 0 && <Notice text="Noch keine Suchen — im Bot ➕ Neue Suche." />}
      {data?.map((r) => (
        <div key={r.id} className={CARD}>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate font-medium">{r.name}</div>
              <div className={HINT}>
                <code>{r.keywords}</code>
                {r.max_price ? ` · bis ${eur(r.max_price)}` : ""}
                {r.location ? ` · 📍 ${r.location}${r.max_distance_km ? ` ±${r.max_distance_km} km` : ""}` : ""}
                {` · ⏱ ${Math.round(r.interval_seconds / 60)} min`}
              </div>
            </div>
            <button
              className={r.is_active ? BTN : `${BTN} opacity-50`}
              disabled={busy === r.id}
              onClick={() => toggle(r.id)}
            >
              {r.is_active ? "🟢 aktiv" : "⚪️ pausiert"}
            </button>
          </div>
        </div>
      ))}
      <Notice text="Bearbeiten & neue Suchen: im Bot unter 📋 Meine Suchen." />
    </Section>
  );
}

function FlipsTab() {
  const { data, error, loading } = useLoad<WaFlips>(() => webapp.flips(), []);
  const s = data?.stats;
  return (
    <Section title="📦 Flips & Gewinn">
      {loading && <Notice text="Lädt…" />}
      {error && <Notice text={`⚠️ ${error}`} />}
      {s && (
        <div className="grid grid-cols-2 gap-3">
          <div className={CARD}>
            <div className={HINT}>Netto-Gewinn gesamt</div>
            <div className="text-2xl font-semibold">{eur(s.net_profit)}</div>
          </div>
          <div className={CARD}>
            <div className={HINT}>Letzte 30 Tage</div>
            <div className="text-2xl font-semibold">{eur(s.net_last_30d)}</div>
          </div>
          <div className={CARD}>
            <div className={HINT}>Verkauft</div>
            <div className="text-2xl font-semibold">{s.sold_count}</div>
            <div className={HINT}>Ø Marge {s.avg_margin_pct == null ? "—" : `${Math.round(s.avg_margin_pct)}%`}</div>
          </div>
          <div className={CARD}>
            <div className={HINT}>Im Lager</div>
            <div className="text-2xl font-semibold">{s.open_count}</div>
            <div className={HINT}>gebunden {eur(s.invested_open)}</div>
          </div>
        </div>
      )}
      {s?.best_title && (
        <Notice text={`🏆 Bester Flip: ${s.best_title} (+${eur(s.best_net)})`} />
      )}
      {data?.open.map((f) => (
        <div key={f.id} className={CARD}>
          <div className="font-medium">{f.title}</div>
          <div className={HINT}>
            gekauft {eur(f.buy_price)} am {dateDE(f.bought_at)}
          </div>
        </div>
      ))}
      <Notice text="Kaufen/Verkaufen buchst du im Bot: 🛒 auf der Karte bzw. /flips." />
    </Section>
  );
}

function PremiumTab({ me }: { me: Me | null }) {
  const { data, error, loading } = useLoad<WaPayment[]>(() => webapp.payments(), []);
  return (
    <Section title="💎 Premium & Zahlungen">
      {me && (
        <div className={CARD}>
          <div className="text-lg font-semibold">
            {me.is_paid ? "💎 Premium aktiv" : "Free-Tarif"}
          </div>
          {me.premium_until && <div className={HINT}>Aktiv bis {dateDE(me.premium_until)}</div>}
          {me.is_paid && (
            <div className={HINT}>
              {me.renews
                ? `🔄 Nächste Abbuchung: ${dateDE(me.next_charge_at)}`
                : "⏳ Verlängert sich nicht (läuft aus)"}
            </div>
          )}
          {me.last_charge_at && <div className={HINT}>💳 Letzte Abbuchung: {dateDE(me.last_charge_at)}</div>}
          {!me.is_paid && (
            <div className={`${HINT} mt-2`}>
              {me.price_stars} ⭐ (~{me.price_eur.toFixed(2)} €)/Monat — Upgrade im Bot mit /premium
            </div>
          )}
        </div>
      )}
      <h3 className="font-semibold">📜 Zahlungsverlauf</h3>
      {loading && <Notice text="Lädt…" />}
      {error && <Notice text={`⚠️ ${error}`} />}
      {data && data.length === 0 && <Notice text="Noch keine Zahlungen." />}
      {data?.map((p) => (
        <div key={p.id} className={`${CARD} flex items-center justify-between`}>
          <div>
            <div className="font-medium">
              {p.provider === "telegram_stars"
                ? `${p.amount_stars} ⭐${p.is_renewal ? " · Verlängerung" : " · Kauf"}`
                : p.provider === "admin_grant"
                  ? "🎁 Geschenk"
                  : p.provider}
              {p.coupon_code ? ` · 🎟 ${p.coupon_code}` : ""}
            </div>
            <div className={HINT}>{new Date(p.created_at).toLocaleString("de-DE")}</div>
          </div>
          <div className={p.refunded ? "text-rose-500" : HINT}>
            {p.refunded ? "erstattet" : p.status}
          </div>
        </div>
      ))}
    </Section>
  );
}

// --- Page -----------------------------------------------------------------------
export function MiniApp() {
  const sdkReady = useTelegramSdk();
  const [tab, setTab] = useState<Tab>("deals");
  const me = useLoad<Me>(() => webapp.me(), [sdkReady]);

  return (
    <div className={`min-h-screen ${BG}`}>
      <header className="sticky top-0 z-10 px-4 pt-4 pb-2 backdrop-blur bg-[var(--tg-theme-bg-color,#f8fafc)]/90">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xl font-bold">🛒 Deal Hunter</div>
            <div className={HINT}>
              {me.data ? `${me.data.name} · ${me.data.is_paid ? "💎 Premium" : "Free"}` : " "}
            </div>
          </div>
        </div>
        <nav className="mt-3 flex gap-2 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`whitespace-nowrap rounded-full px-3 py-1.5 text-sm ${
                tab === t.id ? BTN : `${CARD} !p-0 px-3 py-1.5`
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="space-y-4 px-4 pb-8 pt-2">
        {!sdkReady && <Notice text="Verbinde mit Telegram…" />}
        {me.error && (
          <Notice text={`⚠️ ${me.error} — diese Seite funktioniert nur innerhalb von Telegram (Bot-Menü → 🌐 App).`} />
        )}
        {tab === "deals" && <DealsTab />}
        {tab === "rules" && <RulesTab />}
        {tab === "flips" && <FlipsTab />}
        {tab === "premium" && <PremiumTab me={me.data} />}
      </main>
    </div>
  );
}
