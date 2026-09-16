import { useEffect, useState, type ReactNode } from "react";
import {
  DealCard,
  DealHero,
  DealSkeleton,
  money,
  since,
  type DealLike,
} from "../components/DealCard";
import {
  SDK_URL,
  WebAppError,
  dateDE,
  tg,
  webapp,
  type Me,
  type RuleInput,
  type WaFlips,
  type WaListing,
  type WaPayment,
  type WaRule,
} from "../lib/webapp";

type Tab = "deals" | "rules" | "flips" | "premium";

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: "deals", icon: "🔥", label: "Deals" },
  { id: "rules", icon: "🎯", label: "Suchen" },
  { id: "flips", icon: "📦", label: "Flips" },
  { id: "premium", icon: "💎", label: "Konto" },
];

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

function haptic(style = "light") {
  tg()?.HapticFeedback?.impactOccurred(style);
}

// --- Small building blocks ----------------------------------------------------------
function Screen({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <h2 style={{ fontSize: 17, fontWeight: 620, margin: 0 }}>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** Empty states explain what to do next instead of just stating a fact. */
function EmptyState({ icon, title, hint }: { icon: string; title: string; hint: string }) {
  return (
    <div className="dh-card" style={{ padding: "28px 18px", textAlign: "center" }}>
      <div style={{ fontSize: 30, lineHeight: 1 }}>{icon}</div>
      <div style={{ fontWeight: 600, marginTop: 10 }}>{title}</div>
      <div className="dh-muted" style={{ fontSize: 13, marginTop: 4, lineHeight: 1.45 }}>
        {hint}
      </div>
    </div>
  );
}

function ErrorState({ text }: { text: string }) {
  return (
    <div
      className="dh-card"
      style={{ padding: "12px 14px", fontSize: 13, borderColor: "color-mix(in srgb, var(--dh-steal) 40%, transparent)" }}
    >
      <span style={{ color: "var(--dh-steal)", fontWeight: 600 }}>Fehler</span>{" "}
      <span className="dh-muted">{text}</span>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="dh-card dh-stat">
      <div className="dh-meta">{label}</div>
      <div className="dh-stat-value dh-num" style={{ marginTop: 3 }}>
        {value}
      </div>
      {sub && (
        <div className="dh-muted" style={{ fontSize: 12, marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

// --- Deals ---------------------------------------------------------------------------
function DealsTab() {
  const [favs, setFavs] = useState(false);
  const { data, error, loading } = useLoad<WaListing[]>(() => webapp.listings(favs), [favs]);
  const deals = (data ?? []) as unknown as DealLike[];
  const [hero, ...rest] = deals;

  return (
    <Screen
      title={favs ? "Favoriten" : "Neueste Funde"}
      action={
        <div className="dh-seg">
          <button
            data-active={favs ? 0 : 1}
            onClick={() => {
              haptic();
              setFavs(false);
            }}
          >
            Alle
          </button>
          <button
            data-active={favs ? 1 : 0}
            onClick={() => {
              haptic();
              setFavs(true);
            }}
          >
            ★ Favoriten
          </button>
        </div>
      }
    >
      {loading && (
        <>
          <DealSkeleton />
          <DealSkeleton />
          <DealSkeleton />
        </>
      )}
      {error && <ErrorState text={error} />}
      {!loading && !error && deals.length === 0 && (
        <EmptyState
          icon={favs ? "☆" : "🔍"}
          title={favs ? "Noch nichts gemerkt" : "Noch keine Funde"}
          hint={
            favs
              ? "Tippe auf den Stern an einer Karte, um Angebote hier zu sammeln."
              : "Leg unter „Suchen“ deine erste Suche an — die Treffer landen dann hier und als Nachricht im Chat."
          }
        />
      )}
      {/* The best current find gets the big treatment, the rest stay scannable. */}
      {!loading && hero && !favs && <DealHero deal={hero} />}
      {!loading && (favs ? deals : rest).map((d) => <DealCard key={d.id} deal={d} />)}
    </Screen>
  );
}

// --- Rules ----------------------------------------------------------------------------
const EMPTY_RULE: RuleInput = {
  name: "",
  keywords: "",
  min_price: null,
  max_price: null,
  location: null,
  max_distance_km: null,
  interval_seconds: 600,
  exclude_keywords: [],
};

function toInput(rule: WaRule): RuleInput {
  return {
    name: rule.name,
    keywords: rule.keywords,
    min_price: rule.min_price,
    max_price: rule.max_price,
    location: rule.location,
    max_distance_km: rule.max_distance_km,
    interval_seconds: rule.interval_seconds,
    exclude_keywords: [],
  };
}

function num(value: string): number | null {
  const parsed = Number(value.replace(",", "."));
  return value.trim() === "" || Number.isNaN(parsed) ? null : parsed;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 5 }}>
      <span className="dh-meta">{label}</span>
      {children}
    </label>
  );
}

/** Create/edit form. The bot's wizard asks eight questions; here it is one screen. */
function RuleForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial: { id: number | null; values: RuleInput };
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<RuleInput>(initial.values);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof RuleInput>(key: K, value: RuleInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function save() {
    if (!form.name.trim() || !form.keywords.trim()) {
      setError("Name und Suchbegriffe brauche ich mindestens.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (initial.id === null) await webapp.createRule(form);
      else await webapp.updateRule(initial.id, form);
      haptic("medium");
      onSaved();
    } catch (e) {
      setError(e instanceof WebAppError ? e.message : "Speichern fehlgeschlagen");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dh-card" style={{ padding: 14, display: "grid", gap: 12 }}>
      <div style={{ fontWeight: 620 }}>
        {initial.id === null ? "Neue Suche" : "Suche bearbeiten"}
      </div>

      <Field label="NAME">
        <input
          className="dh-input"
          placeholder="Tesla Model 3"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
        />
      </Field>

      <Field label="SUCHBEGRIFFE">
        <input
          className="dh-input"
          placeholder="tesla model 3 performance"
          value={form.keywords}
          onChange={(e) => set("keywords", e.target.value)}
        />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="PREIS VON">
          <input
            className="dh-input dh-num"
            inputMode="decimal"
            placeholder="—"
            value={form.min_price ?? ""}
            onChange={(e) => set("min_price", num(e.target.value))}
          />
        </Field>
        <Field label="PREIS BIS">
          <input
            className="dh-input dh-num"
            inputMode="decimal"
            placeholder="—"
            value={form.max_price ?? ""}
            onChange={(e) => set("max_price", num(e.target.value))}
          />
        </Field>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="PLZ ODER ORT">
          <input
            className="dh-input"
            placeholder="67550"
            value={form.location ?? ""}
            onChange={(e) => set("location", e.target.value || null)}
          />
        </Field>
        <Field label="UMKREIS">
          <select
            className="dh-input"
            value={form.max_distance_km ?? ""}
            onChange={(e) =>
              set("max_distance_km", e.target.value === "" ? null : Number(e.target.value))
            }
          >
            <option value="">egal</option>
            <option value="25">25 km</option>
            <option value="50">50 km</option>
            <option value="100">100 km</option>
            <option value="200">200 km</option>
          </select>
        </Field>
      </div>

      <Field label="WIE OFT PRÜFEN">
        <select
          className="dh-input"
          value={form.interval_seconds}
          onChange={(e) => set("interval_seconds", Number(e.target.value))}
        >
          <option value={60}>jede Minute — Premium</option>
          <option value={300}>alle 5 Minuten</option>
          <option value={600}>alle 10 Minuten</option>
          <option value={1800}>alle 30 Minuten</option>
          <option value={3600}>stündlich</option>
        </select>
      </Field>

      {error && <ErrorState text={error} />}

      <div style={{ display: "flex", gap: 8 }}>
        <button className="dh-btn" disabled={saving} onClick={save} style={{ flex: 1 }}>
          {saving ? "Speichert…" : "Speichern"}
        </button>
        <button className="dh-btn dh-btn-quiet" disabled={saving} onClick={onCancel}>
          Abbrechen
        </button>
      </div>

      <div className="dh-muted" style={{ fontSize: 12 }}>
        Das Intervall wird automatisch an deinen Tarif angepasst.
      </div>
    </div>
  );
}

function everyText(seconds: number): string {
  if (seconds < 120) return "jede Minute";
  if (seconds < 3600) return `alle ${Math.round(seconds / 60)} Min`;
  return `alle ${Math.round(seconds / 3600)} Std`;
}

function RuleRow({
  rule,
  busy,
  onToggle,
  onEdit,
  onDelete,
}: {
  rule: WaRule;
  busy: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const criteria = [
    rule.max_price ? `bis ${money(rule.max_price)}` : null,
    rule.location ? `${rule.location}${rule.max_distance_km ? ` +${rule.max_distance_km} km` : ""}` : null,
    everyText(rule.interval_seconds),
  ].filter(Boolean);

  return (
    <div
      className="dh-card"
      style={{ ["--rail" as string]: rule.is_active ? "var(--dh-great)" : "var(--dh-overpriced)" }}
    >
      <div style={{ padding: "11px 12px 11px 15px" }}>
        <div style={{ position: "absolute", inset: "0 auto 0 0", width: 3, background: "var(--rail)" }} />
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{rule.name}</div>
            <div className="dh-meta" style={{ marginTop: 3 }}>
              {rule.keywords}
            </div>
          </div>
          <button
            className="dh-btn dh-btn-sm dh-btn-quiet"
            disabled={busy}
            onClick={onToggle}
            style={{
              color: rule.is_active ? "var(--dh-great)" : "var(--dh-muted)",
              borderColor: "var(--dh-line)",
              whiteSpace: "nowrap",
            }}
          >
            {rule.is_active ? "● aktiv" : "○ Pause"}
          </button>
        </div>

        <div style={{ display: "flex", gap: 6, marginTop: 9, flexWrap: "wrap" }}>
          {criteria.map((c) => (
            <span key={c as string} className="dh-tag">
              {c}
            </span>
          ))}
        </div>

        <div style={{ display: "flex", gap: 14, marginTop: 10 }}>
          <button
            onClick={onEdit}
            style={{ border: 0, background: "none", padding: 0, color: "var(--dh-accent)", fontSize: 13, fontWeight: 550, cursor: "pointer" }}
          >
            Bearbeiten
          </button>
          <button
            onClick={onDelete}
            disabled={busy}
            style={{ border: 0, background: "none", padding: 0, color: "var(--dh-muted)", fontSize: 13, cursor: "pointer" }}
          >
            Löschen
          </button>
        </div>
      </div>
    </div>
  );
}

function RulesTab() {
  const [version, setVersion] = useState(0);
  const { data, error, loading } = useLoad<WaRule[]>(() => webapp.rules(), [version]);
  const [busy, setBusy] = useState<number | null>(null);
  const [editing, setEditing] = useState<{ id: number | null; values: RuleInput } | null>(null);

  const reload = () => setVersion((v) => v + 1);

  async function toggle(id: number) {
    setBusy(id);
    try {
      await webapp.toggleRule(id);
      haptic();
      reload();
    } finally {
      setBusy(null);
    }
  }

  async function remove(id: number, name: string) {
    if (!window.confirm(`Suche „${name}“ löschen?`)) return;
    setBusy(id);
    try {
      await webapp.deleteRule(id);
      reload();
    } finally {
      setBusy(null);
    }
  }

  if (editing) {
    return (
      <Screen title="Suchen">
        <RuleForm
          initial={editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      </Screen>
    );
  }

  const rules = data ?? [];
  const active = rules.filter((r) => r.is_active).length;

  return (
    <Screen
      title="Suchen"
      action={
        rules.length > 0 ? (
          <button className="dh-btn dh-btn-sm" onClick={() => setEditing({ id: null, values: EMPTY_RULE })}>
            + Neu
          </button>
        ) : undefined
      }
    >
      {loading && (
        <>
          <div className="dh-card dh-skel" style={{ height: 112 }} />
          <div className="dh-card dh-skel" style={{ height: 112 }} />
        </>
      )}
      {error && <ErrorState text={error} />}
      {!loading && rules.length === 0 && (
        <>
          <EmptyState
            icon="🎯"
            title="Noch keine Suche"
            hint="Sag mir, wonach ich suchen soll — ich prüfe die Marktplätze rund um die Uhr und melde mich, sobald etwas unter Marktpreis auftaucht."
          />
          <button className="dh-btn" onClick={() => setEditing({ id: null, values: EMPTY_RULE })}>
            Erste Suche anlegen
          </button>
        </>
      )}
      {!loading && rules.length > 0 && (
        <div className="dh-meta">
          {active} von {rules.length} aktiv
        </div>
      )}
      {rules.map((r) => (
        <RuleRow
          key={r.id}
          rule={r}
          busy={busy === r.id}
          onToggle={() => toggle(r.id)}
          onEdit={() => setEditing({ id: r.id, values: toInput(r) })}
          onDelete={() => remove(r.id, r.name)}
        />
      ))}
    </Screen>
  );
}

// --- Flips ----------------------------------------------------------------------------
function FlipsTab() {
  const { data, error, loading } = useLoad<WaFlips>(() => webapp.flips(), []);
  const s = data?.stats;

  return (
    <Screen title="Flips & Gewinn">
      {loading && <div className="dh-card dh-skel" style={{ height: 150 }} />}
      {error && <ErrorState text={error} />}

      {s && (
        <>
          <div
            className="dh-card"
            style={{ padding: "16px 14px", ["--rail" as string]: "var(--dh-great)" }}
          >
            <div style={{ position: "absolute", inset: "0 auto 0 0", width: 3, background: "var(--rail)" }} />
            <div className="dh-meta">NETTO-GEWINN GESAMT</div>
            <div className="dh-num" style={{ fontSize: 34, fontWeight: 680, lineHeight: 1.1, marginTop: 4 }}>
              {money(s.net_profit)}
            </div>
            <div className="dh-muted" style={{ fontSize: 13, marginTop: 4 }}>
              davon {money(s.net_last_30d)} in den letzten 30 Tagen
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Stat
              label="VERKAUFT"
              value={String(s.sold_count)}
              sub={s.avg_margin_pct == null ? "—" : `Ø Marge ${Math.round(s.avg_margin_pct)} %`}
            />
            <Stat label="IM LAGER" value={String(s.open_count)} sub={`${money(s.invested_open)} gebunden`} />
          </div>

          {s.best_title && (
            <div className="dh-card" style={{ padding: "11px 13px" }}>
              <div className="dh-meta">BESTER FLIP</div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginTop: 3 }}>
                <span style={{ fontWeight: 560, fontSize: 14 }}>{s.best_title}</span>
                <span className="dh-num" style={{ color: "var(--dh-great)", fontWeight: 650 }}>
                  +{money(s.best_net)}
                </span>
              </div>
            </div>
          )}
        </>
      )}

      {data && data.open.length > 0 && (
        <>
          <div className="dh-meta" style={{ marginTop: 4 }}>
            OFFEN IM LAGER
          </div>
          {data.open.map((f) => (
            <div key={f.id} className="dh-card" style={{ padding: "11px 13px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                <span style={{ fontWeight: 560, fontSize: 14 }}>{f.title}</span>
                <span className="dh-num" style={{ fontWeight: 620 }}>
                  {money(f.buy_price)}
                </span>
              </div>
              <div className="dh-meta" style={{ marginTop: 3 }}>
                gekauft {since(f.bought_at)}
              </div>
            </div>
          ))}
        </>
      )}

      {!loading && !error && s?.sold_count === 0 && data?.open.length === 0 && (
        <EmptyState
          icon="📦"
          title="Noch keine Flips"
          hint="Wenn du ein gefundenes Angebot kaufst, tippe im Chat auf 🛒 — danach rechne ich dir Gewinn und Marge automatisch aus."
        />
      )}

      <div className="dh-muted" style={{ fontSize: 12 }}>
        Kaufen und Verkaufen buchst du im Chat: 🛒 auf der Karte oder /flips.
      </div>
    </Screen>
  );
}

// --- Account ---------------------------------------------------------------------------
const PROVIDER_LABEL: Record<string, string> = {
  telegram_stars: "Telegram Stars",
  admin_grant: "Geschenk",
  trial: "Testphase",
  coupon: "Gutschein",
  referral: "Empfehlung",
};

function PremiumTab({ me }: { me: Me | null }) {
  const { data, error, loading } = useLoad<WaPayment[]>(() => webapp.payments(), []);

  return (
    <Screen title="Konto">
      {me && (
        <div
          className="dh-card"
          style={{
            padding: "16px 14px",
            ["--rail" as string]: me.is_paid ? "var(--dh-great)" : "var(--dh-overpriced)",
          }}
        >
          <div style={{ position: "absolute", inset: "0 auto 0 0", width: 3, background: "var(--rail)" }} />
          <div className="dh-meta">TARIF</div>
          <div style={{ fontSize: 22, fontWeight: 650, marginTop: 3 }}>
            {me.is_paid ? me.tier.charAt(0).toUpperCase() + me.tier.slice(1) : "Free"}
          </div>

          {me.is_paid ? (
            <div style={{ display: "grid", gap: 4, marginTop: 10 }}>
              <Line label="Aktiv bis" value={dateDE(me.premium_until)} />
              <Line
                label={me.renews ? "Nächste Abbuchung" : "Läuft aus am"}
                value={dateDE(me.renews ? me.next_charge_at : me.premium_until)}
              />
              {me.last_charge_at && <Line label="Letzte Abbuchung" value={dateDE(me.last_charge_at)} />}
            </div>
          ) : (
            <div className="dh-muted" style={{ fontSize: 13, marginTop: 8, lineHeight: 1.45 }}>
              Mehr Suchen und Prüfung im Minutentakt gibt es ab {me.price_stars} ⭐ (~
              {me.price_eur.toFixed(2)} €) im Monat. Buchen im Chat mit /premium.
            </div>
          )}
        </div>
      )}

      <div className="dh-meta" style={{ marginTop: 4 }}>
        ZAHLUNGEN
      </div>
      {loading && <div className="dh-card dh-skel" style={{ height: 70 }} />}
      {error && <ErrorState text={error} />}
      {data && data.length === 0 && (
        <EmptyState icon="🧾" title="Noch keine Zahlungen" hint="Hier erscheint jede Abbuchung mit Datum und Betrag." />
      )}
      {data?.map((p) => (
        <div key={p.id} className="dh-card" style={{ padding: "11px 13px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontWeight: 560, fontSize: 14 }}>
              {p.amount_stars > 0 ? `${p.amount_stars} ⭐` : PROVIDER_LABEL[p.provider] ?? p.provider}
              {p.coupon_code ? ` · ${p.coupon_code}` : ""}
            </span>
            <span
              className="dh-meta"
              style={{ color: p.refunded ? "var(--dh-steal)" : undefined }}
            >
              {p.refunded ? "erstattet" : p.is_renewal ? "Verlängerung" : p.status === "granted" ? "geschenkt" : "bezahlt"}
            </span>
          </div>
          <div className="dh-meta" style={{ marginTop: 3 }}>
            {new Date(p.created_at).toLocaleDateString("de-DE", {
              day: "2-digit",
              month: "long",
              year: "numeric",
            })}
            {p.amount_eur > 0 ? ` · ${p.amount_eur.toFixed(2)} €` : ""}
          </div>
        </div>
      ))}
    </Screen>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
      <span className="dh-muted">{label}</span>
      <span className="dh-num" style={{ fontWeight: 560 }}>
        {value}
      </span>
    </div>
  );
}

// --- Page -----------------------------------------------------------------------------
export function MiniApp() {
  const sdkReady = useTelegramSdk();
  const [tab, setTab] = useState<Tab>("deals");
  const me = useLoad<Me>(() => webapp.me(), [sdkReady]);

  return (
    <div className="dh-app" style={{ paddingBottom: 78 }}>
      <header className="dh-header">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: 17, fontWeight: 700, letterSpacing: "-0.02em" }}>Deal Hunter</span>
            {me.data && (
              <span
                className="dh-meta"
                style={{
                  padding: "1px 6px",
                  border: "1px solid var(--dh-line)",
                  borderRadius: 5,
                  color: me.data.is_paid ? "var(--dh-great)" : "var(--dh-muted)",
                  borderColor: me.data.is_paid ? "color-mix(in srgb, var(--dh-great) 45%, transparent)" : undefined,
                }}
              >
                {me.data.is_paid ? me.data.tier.toUpperCase() : "FREE"}
              </span>
            )}
          </div>
          {me.data && <span className="dh-meta">{me.data.name}</span>}
        </div>
      </header>

      <main style={{ padding: "12px 14px 24px", display: "grid", gap: 10 }}>
        {!sdkReady && <div className="dh-card dh-skel" style={{ height: 46 }} />}
        {me.error && (
          <ErrorState text={`${me.error} — diese Seite läuft nur in Telegram (Bot-Menü → App).`} />
        )}
        {tab === "deals" && <DealsTab />}
        {tab === "rules" && <RulesTab />}
        {tab === "flips" && <FlipsTab />}
        {tab === "premium" && <PremiumTab me={me.data} />}
      </main>

      <nav className="dh-tabbar">
        {TABS.map((t) => (
          <button
            key={t.id}
            data-active={tab === t.id ? 1 : 0}
            onClick={() => {
              haptic();
              setTab(t.id);
            }}
          >
            <span className="dh-tab-icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
