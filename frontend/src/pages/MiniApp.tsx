import { useEffect, useState, type ReactNode } from "react";
import {
  DealHero,
  DealRow,
  DealRowSkeleton,
  money,
  since,
  type DealLike,
} from "../components/DealCard";
import {
  IconAlert,
  IconBox,
  IconCancel,
  IconCheck,
  IconPause,
  IconPencil,
  IconPlus,
  IconReceipt,
  IconSearch,
  IconStar,
  IconTag,
  IconTrash,
  IconWallet,
} from "../components/icons";
import {
  SDK_URL,
  WebAppError,
  dateDE,
  everyMinutes,
  quotaShare,
  quotaText,
  tg,
  webapp,
  type CancelKind,
  type Me,
  type RuleInput,
  type WaCancel,
  type WaFlips,
  type WaLevel,
  type WaListing,
  type WaPayment,
  type WaQuota,
  type WaRule,
} from "../lib/webapp";

type Tab = "deals" | "rules" | "flips" | "account";

const TABS: { id: Tab; label: string; Icon: (p: { size?: number }) => JSX.Element }[] = [
  { id: "deals", label: "Funde", Icon: IconTag },
  { id: "rules", label: "Suchen", Icon: IconSearch },
  { id: "flips", label: "Flips", Icon: IconBox },
  { id: "account", label: "Konto", Icon: IconWallet },
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

const haptic = (style = "light") => tg()?.HapticFeedback?.impactOccurred(style);

// --- Building blocks ------------------------------------------------------------------
function Section({
  title,
  action,
  children,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {(title || action) && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, minHeight: 32 }}>
          {title ? <h2 className="dh-h2">{title}</h2> : <span />}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

function Empty({
  icon,
  title,
  hint,
  action,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <div className="dh-group">
      <div className="dh-empty">
        <div className="dh-empty-icon">{icon}</div>
        <div style={{ fontSize: 15, fontWeight: 500 }}>{title}</div>
        <div className="dh-muted" style={{ fontSize: 13, marginTop: 5, maxWidth: 280, lineHeight: 1.5 }}>
          {hint}
        </div>
        {action && <div style={{ marginTop: 16 }}>{action}</div>}
      </div>
    </div>
  );
}

function ErrorNote({ text }: { text: string }) {
  return (
    <div className="dh-group">
      <div className="dh-row" style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <span style={{ color: "var(--dh-q-steal)", flex: "none", marginTop: 1 }}>
          <IconAlert size={18} />
        </span>
        <span style={{ fontSize: 13.5, lineHeight: 1.45 }}>{text}</span>
      </div>
    </div>
  );
}

/** Label above, value below — the shape every figure on the screen uses. */
function Figure({ label, value, sub, small }: { label: string; value: string; sub?: string; small?: boolean }) {
  return (
    <div className="dh-row" style={{ padding: "13px 14px" }}>
      <div className="dh-label">{label}</div>
      <div className={small ? "dh-figure-sm dh-num" : "dh-figure dh-num"} style={{ marginTop: 5 }}>
        {value}
      </div>
      {sub && (
        <div className="dh-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

// --- Deals -----------------------------------------------------------------------------
function DealsTab() {
  const [favs, setFavs] = useState(false);
  const { data, error, loading } = useLoad<WaListing[]>(() => webapp.listings(favs), [favs]);
  const deals = (data ?? []) as unknown as DealLike[];
  const [hero, ...rest] = deals;
  const list = favs ? deals : rest;

  return (
    <Section
      title={favs ? "Favoriten" : "Neueste Funde"}
      action={
        <div className="dh-seg">
          <button data-active={favs ? 0 : 1} onClick={() => { haptic(); setFavs(false); }}>
            Alle
          </button>
          <button data-active={favs ? 1 : 0} onClick={() => { haptic(); setFavs(true); }}>
            Favoriten
          </button>
        </div>
      }
    >
      {loading && (
        <div className="dh-group">
          <DealRowSkeleton />
          <DealRowSkeleton />
          <DealRowSkeleton />
        </div>
      )}
      {error && <ErrorNote text={error} />}
      {!loading && !error && deals.length === 0 && (
        <Empty
          icon={favs ? <IconStar size={20} /> : <IconSearch size={20} />}
          title={favs ? "Noch nichts gemerkt" : "Noch keine Funde"}
          hint={
            favs
              ? "Tippe den Stern an einem Fund an, um ihn hier zu sammeln."
              : "Lege unter Suchen an, wonach ich Ausschau halten soll. Treffer erscheinen hier und als Nachricht im Chat."
          }
        />
      )}
      {!loading && !favs && hero && <DealHero deal={hero} />}
      {!loading && list.length > 0 && (
        <div className="dh-group">
          {list.map((d) => (
            <DealRow key={d.id} deal={d} />
          ))}
        </div>
      )}
    </Section>
  );
}

// --- Rules -----------------------------------------------------------------------------
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

const num = (value: string): number | null => {
  const parsed = Number(value.replace(",", "."));
  return value.trim() === "" || Number.isNaN(parsed) ? null : parsed;
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 6 }}>
      <span className="dh-label">{label}</span>
      {children}
    </label>
  );
}

function everyText(seconds: number): string {
  if (seconds < 120) return "jede Minute";
  if (seconds < 3600) return `alle ${Math.round(seconds / 60)} Min`;
  return seconds === 3600 ? "stündlich" : `alle ${Math.round(seconds / 3600)} Std`;
}

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
    <Section title={initial.id === null ? "Neue Suche" : "Suche bearbeiten"}>
      <div className="dh-group">
        <div className="dh-row" style={{ display: "grid", gap: 14, padding: 16 }}>
          <Field label="Name">
            <input
              className="dh-input"
              placeholder="Tesla Model 3"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </Field>

          <Field label="Suchbegriffe">
            <input
              className="dh-input"
              placeholder="tesla model 3 performance"
              value={form.keywords}
              onChange={(e) => set("keywords", e.target.value)}
            />
          </Field>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Preis von">
              <input
                className="dh-input dh-num"
                inputMode="decimal"
                placeholder="—"
                value={form.min_price ?? ""}
                onChange={(e) => set("min_price", num(e.target.value))}
              />
            </Field>
            <Field label="Preis bis">
              <input
                className="dh-input dh-num"
                inputMode="decimal"
                placeholder="—"
                value={form.max_price ?? ""}
                onChange={(e) => set("max_price", num(e.target.value))}
              />
            </Field>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="PLZ oder Ort">
              <input
                className="dh-input"
                placeholder="67550"
                value={form.location ?? ""}
                onChange={(e) => set("location", e.target.value || null)}
              />
            </Field>
            <Field label="Umkreis">
              <select
                className="dh-select"
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

          <Field label="Prüfen">
            <select
              className="dh-select"
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
        </div>
      </div>

      {error && <ErrorNote text={error} />}

      <div style={{ display: "flex", gap: 10 }}>
        <button className="dh-btn" disabled={saving} onClick={save} style={{ flex: 1 }}>
          {saving ? "Speichert…" : "Speichern"}
        </button>
        <button className="dh-btn dh-btn-quiet" disabled={saving} onClick={onCancel}>
          Abbrechen
        </button>
      </div>

      <div className="dh-muted" style={{ fontSize: 12.5 }}>
        Das Prüf-Intervall wird automatisch an deinen Tarif angepasst.
      </div>
    </Section>
  );
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
  ].filter(Boolean) as string[];

  return (
    <div className="dh-row">
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span
              className="dh-dot"
              style={{
                ["--q" as string]: rule.is_active ? "var(--dh-q-great)" : "var(--dh-q-none)",
                margin: 0,
              }}
            />
            <span style={{ fontSize: 15, fontWeight: 500 }}>{rule.name}</span>
          </div>
          <div className="dh-meta" style={{ marginTop: 4 }}>
            {rule.keywords}
          </div>
        </div>
        <button
          className="dh-btn dh-btn-sm dh-btn-quiet"
          disabled={busy}
          onClick={onToggle}
          title={rule.is_active ? "Pausieren" : "Aktivieren"}
          style={{ flex: "none", width: 34, padding: 0, color: "var(--dh-muted)" }}
        >
          {rule.is_active ? <IconPause size={15} /> : <IconCheck size={15} />}
        </button>
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
        {criteria.map((c) => (
          <span key={c} className="dh-chip">
            {c}
          </span>
        ))}
      </div>

      <div style={{ display: "flex", gap: 18, marginTop: 12 }}>
        <button className="dh-link" onClick={onEdit}>
          <IconPencil size={15} />
          Bearbeiten
        </button>
        <button className="dh-link dh-link-quiet" disabled={busy} onClick={onDelete}>
          <IconTrash size={15} />
          Löschen
        </button>
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
      <RuleForm
        initial={editing}
        onCancel={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          reload();
        }}
      />
    );
  }

  const rules = data ?? [];
  const active = rules.filter((r) => r.is_active).length;

  return (
    <Section
      title="Suchen"
      action={
        rules.length > 0 ? (
          <button className="dh-btn dh-btn-sm" onClick={() => setEditing({ id: null, values: EMPTY_RULE })}>
            <IconPlus size={15} />
            Neu
          </button>
        ) : undefined
      }
    >
      {loading && (
        <div className="dh-group">
          <div className="dh-row dh-skel" style={{ height: 104, borderRadius: 0 }} />
        </div>
      )}
      {error && <ErrorNote text={error} />}
      {!loading && rules.length === 0 && (
        <Empty
          icon={<IconSearch size={20} />}
          title="Noch keine Suche"
          hint="Sag mir, wonach ich suchen soll. Ich prüfe die Marktplätze rund um die Uhr und melde mich, sobald etwas deutlich unter Marktpreis auftaucht."
          action={
            <button className="dh-btn" onClick={() => setEditing({ id: null, values: EMPTY_RULE })}>
              <IconPlus size={16} />
              Erste Suche anlegen
            </button>
          }
        />
      )}
      {!loading && rules.length > 0 && (
        <>
          <div className="dh-label">
            {active} von {rules.length} aktiv
          </div>
          <div className="dh-group">
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
          </div>
        </>
      )}
    </Section>
  );
}

// --- Flips ------------------------------------------------------------------------------
function FlipsTab() {
  const { data, error, loading } = useLoad<WaFlips>(() => webapp.flips(), []);
  const s = data?.stats;

  return (
    <Section title="Flips">
      {loading && (
        <div className="dh-group">
          <div className="dh-row dh-skel" style={{ height: 96, borderRadius: 0 }} />
        </div>
      )}
      {error && <ErrorNote text={error} />}

      {s && (
        <>
          <div className="dh-group">
            <Figure
              label="Netto-Gewinn gesamt"
              value={money(s.net_profit)}
              sub={`davon ${money(s.net_last_30d)} in den letzten 30 Tagen`}
            />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr" }}>
              <Figure
                label="Verkauft"
                small
                value={String(s.sold_count)}
                sub={s.avg_margin_pct == null ? "—" : `Ø Marge ${Math.round(s.avg_margin_pct)} %`}
              />
              <div style={{ borderLeft: "1px solid var(--dh-hairline)" }}>
                <Figure
                  label="Im Lager"
                  small
                  value={String(s.open_count)}
                  sub={`${money(s.invested_open)} gebunden`}
                />
              </div>
            </div>
            {s.best_title && (
              <div className="dh-row" style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div className="dh-label">Bester Flip</div>
                  <div style={{ fontSize: 14.5, fontWeight: 500, marginTop: 4 }}>{s.best_title}</div>
                </div>
                <span className="dh-num" style={{ color: "var(--dh-save)", fontWeight: 600, alignSelf: "flex-end" }}>
                  +{money(s.best_net)}
                </span>
              </div>
            )}
          </div>

          {data && data.open.length > 0 && (
            <>
              <div className="dh-label">Offen im Lager</div>
              <div className="dh-group">
                {data.open.map((f) => (
                  <div
                    key={f.id}
                    className="dh-row"
                    style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 14.5, fontWeight: 500 }}>{f.title}</div>
                      <div className="dh-meta" style={{ marginTop: 4 }}>
                        gekauft {since(f.bought_at)}
                      </div>
                    </div>
                    <span className="dh-num" style={{ fontWeight: 600 }}>
                      {money(f.buy_price)}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {!loading && !error && s?.sold_count === 0 && data?.open.length === 0 && (
        <Empty
          icon={<IconBox size={20} />}
          title="Noch keine Flips"
          hint="Kaufst du einen Fund, tippe im Chat auf Gekauft — danach rechne ich Gewinn und Marge automatisch aus."
        />
      )}

      <div className="dh-muted" style={{ fontSize: 12.5 }}>
        Käufe und Verkäufe buchst du im Chat mit /flips.
      </div>
    </Section>
  );
}

// --- Account ----------------------------------------------------------------------------
const PROVIDER_LABEL: Record<string, string> = {
  telegram_stars: "Telegram Stars",
  admin_grant: "Geschenk",
  trial: "Testphase",
  coupon: "Gutschein",
  referral: "Empfehlung",
};

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13.5 }}>
      <span className="dh-muted">{label}</span>
      <span className="dh-num" style={{ fontWeight: 500 }}>
        {value}
      </span>
    </div>
  );
}

/** How full one quota is. A hairline track, no label of its own — the row says it. */
function QuotaBar({ quota }: { quota: WaQuota }) {
  const share = quotaShare(quota);
  return (
    <div
      style={{
        height: 3,
        borderRadius: 2,
        marginTop: 9,
        background: "var(--dh-fill)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${Math.max(quota.used > 0 ? 3 : 0, share * 100)}%`,
          height: "100%",
          background: quota.exhausted ? "var(--dh-warn)" : "var(--dh-accent)",
          opacity: quota.unlimited ? 0.3 : 1,
        }}
      />
    </div>
  );
}

function UsageRow({ quota }: { quota: WaQuota }) {
  const left = quota.unlimited
    ? `${quota.used} genutzt`
    : quota.exhausted
      ? "aufgebraucht"
      : `${quota.remaining} übrig`;

  return (
    <div className="dh-row">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
        <span style={{ fontSize: 14.5, fontWeight: 500 }}>{quota.label}</span>
        <span className="dh-num" style={{ fontSize: 13.5, fontWeight: 500 }}>
          {quota.unlimited ? quotaText(-1) : `${quota.used} / ${quota.limit}`}
        </span>
      </div>
      <QuotaBar quota={quota} />
      <div className="dh-meta" style={{ marginTop: 7 }}>
        {quota.window} · {left}
      </div>
    </div>
  );
}

function LevelRow({ level, current, added }: { level: WaLevel; current: boolean; added: string[] }) {
  const facts = [
    `${level.max_rules} Suchen`,
    `alle ${everyMinutes(level.base_interval_seconds)}`,
    level.fast_slots > 0
      ? `${level.fast_slots} Schnell-Slots ab ${everyMinutes(level.min_interval_seconds)}`
      : "keine Schnell-Slots",
    `${quotaText(level.daily_notifications)} Karten/Tag`,
    `${quotaText(level.photo_evals_per_month)} Fotos/Monat`,
    `${quotaText(level.quick_searches_per_day)} Schnell-Suchen/Tag`,
    `Verlauf ${quotaText(level.history_days, " Tage")}`,
  ];

  return (
    <div className="dh-row">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
          <span style={{ fontSize: 14.5, fontWeight: 500 }}>{level.label}</span>
          {current && <span className="dh-pill">aktuell</span>}
        </span>
        <span className="dh-num" style={{ fontSize: 13.5, fontWeight: 500, flex: "none" }}>
          {level.price_stars > 0 ? `${level.price_stars} Stars` : "kostenlos"}
        </span>
      </div>

      <div className="dh-muted" style={{ fontSize: 12.5, marginTop: 6, lineHeight: 1.5 }}>
        {facts.join(" · ")}
      </div>

      {added.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginTop: 9, flexWrap: "wrap" }}>
          {added.map((f) => (
            <span key={f} className="dh-chip">
              {f}
            </span>
          ))}
        </div>
      )}

      {level.note && (
        <div className="dh-meta" style={{ marginTop: 8, whiteSpace: "normal", color: "var(--dh-warn)" }}>
          {level.note}
        </div>
      )}
    </div>
  );
}

/** Cancelling, in two steps.
 *
 * The trigger stays a quiet bordered button: giving premium back is never the
 * action the screen is asking for. The server decides WHICH of the two
 * cancellations applies (stop the Stars renewal, or end a premium nobody is
 * charged for) — the app only words it.
 */
function CancelPremium({
  kind,
  activeUntil,
  result,
  onDone,
}: {
  kind: CancelKind | null;
  activeUntil: string | null;
  result: WaCancel | null;
  onDone: (result: WaCancel) => void;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const renewal = kind === "renewal";

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const res = await webapp.cancelSubscription();
      haptic("medium");
      setAsking(false);
      onDone(res);
    } catch (e) {
      setError(e instanceof WebAppError ? e.message : "Kündigen hat nicht geklappt.");
    } finally {
      setBusy(false);
    }
  }

  // Done: the fresh state is already on screen above, this only says what happened.
  if (result) {
    return (
      <div className="dh-row" style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
        <span style={{ color: "var(--dh-muted)", flex: "none", marginTop: 1 }}>
          <IconCheck size={16} />
        </span>
        <span style={{ fontSize: 13, lineHeight: 1.5 }}>{result.detail}</span>
      </div>
    );
  }

  return (
    <div className="dh-row">
      {asking ? (
        <>
          <div style={{ fontSize: 14, fontWeight: 500 }}>
            {renewal ? "Abo wirklich kündigen?" : "Premium wirklich beenden?"}
          </div>
          <div className="dh-muted" style={{ fontSize: 13, marginTop: 5, lineHeight: 1.5 }}>
            {renewal
              ? `Dein Premium bleibt bis ${dateDE(activeUntil)} voll aktiv — es verlängert sich danach nur nicht mehr und es wird nichts mehr abgebucht.`
              : "Für dieses Premium wird nichts abgebucht (Test, Geschenk oder Gutschein). Beenden heißt: ab sofort wieder im Free-Tarif."}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              className="dh-btn dh-btn-sm dh-btn-quiet"
              disabled={busy}
              onClick={confirm}
              style={{
                color: "var(--dh-warn)",
                borderColor: "color-mix(in srgb, var(--dh-warn) 45%, transparent)",
              }}
            >
              {busy ? "Moment…" : renewal ? "Ja, kündigen" : "Ja, beenden"}
            </button>
            <button
              className="dh-btn dh-btn-sm dh-btn-quiet"
              disabled={busy}
              onClick={() => setAsking(false)}
              style={{ color: "var(--dh-muted)" }}
            >
              Zurück
            </button>
          </div>
        </>
      ) : (
        <button
          className="dh-btn dh-btn-sm dh-btn-quiet"
          onClick={() => {
            haptic();
            setAsking(true);
          }}
          style={{ color: "var(--dh-muted)" }}
        >
          <IconCancel size={15} />
          {renewal ? "Abo kündigen" : "Premium beenden"}
        </button>
      )}

      {error && (
        <div style={{ fontSize: 13, marginTop: 10, lineHeight: 1.5, color: "var(--dh-warn)" }}>
          {error}
        </div>
      )}
    </div>
  );
}

function AccountTab({ me, onChanged }: { me: Me | null; onChanged: () => void }) {
  const { data, error, loading } = useLoad<WaPayment[]>(() => webapp.payments(), []);
  const [cancelled, setCancelled] = useState<WaCancel | null>(null);

  return (
    <Section title="Konto">
      {me && (
        <div className="dh-group">
          <div className="dh-row" style={{ padding: "14px 14px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div className="dh-label">Tarif</div>
              <span className="dh-pill">{me.entitlements.label}</span>
            </div>
            <div className="dh-figure-sm" style={{ marginTop: 6, fontSize: 22 }}>
              {me.entitlements.label}
            </div>

            {me.is_paid ? (
              <div style={{ display: "grid", gap: 7, marginTop: 13 }}>
                <Line label="Aktiv bis" value={dateDE(me.premium_until)} />
                <Line
                  label={me.renews ? "Nächste Abbuchung" : "Läuft aus am"}
                  value={dateDE(me.renews ? me.next_charge_at : me.premium_until)}
                />
                {me.last_charge_at && <Line label="Letzte Abbuchung" value={dateDE(me.last_charge_at)} />}
              </div>
            ) : (
              <div className="dh-muted" style={{ fontSize: 13.5, marginTop: 9, lineHeight: 1.5 }}>
                Mehr Suchen und Prüfung im Minutentakt ab {me.price_stars} Stars (~
                {me.price_eur.toFixed(2)} €) im Monat. Buchen im Chat mit /premium.
              </div>
            )}
          </div>

          {(me.can_cancel || cancelled) && (
            <CancelPremium
              kind={me.cancel_kind}
              activeUntil={me.premium_until}
              result={cancelled}
              onDone={(res) => {
                setCancelled(res);
                onChanged(); // reloads /me — the lines above show the new state
              }}
            />
          )}
        </div>
      )}

      {me && me.usage.length > 0 && (
        <>
          <div className="dh-label">Verbrauch</div>
          <div className="dh-group">
            {me.usage.map((q) => (
              <UsageRow key={q.kind} quota={q} />
            ))}
          </div>
        </>
      )}

      {me && me.levels.length > 0 && (
        <>
          <div className="dh-label">Stufen</div>
          <div className="dh-group">
            {me.levels.map((level, i) => (
              <LevelRow
                key={level.tier}
                level={level}
                current={level.tier === me.entitlements.tier}
                added={level.features.filter((f) => !(me.levels[i - 1]?.features ?? []).includes(f))}
              />
            ))}
          </div>
          <div className="dh-muted" style={{ fontSize: 12.5 }}>
            Stufe wechseln im Chat mit /premium, Verbrauch im Detail mit /usage.
          </div>
        </>
      )}

      <div className="dh-label">Zahlungen</div>
      {loading && (
        <div className="dh-group">
          <div className="dh-row dh-skel" style={{ height: 62, borderRadius: 0 }} />
        </div>
      )}
      {error && <ErrorNote text={error} />}
      {data && data.length === 0 && (
        <Empty
          icon={<IconReceipt size={20} />}
          title="Noch keine Zahlungen"
          hint="Hier erscheint jede Abbuchung mit Datum und Betrag."
        />
      )}
      {data && data.length > 0 && (
        <div className="dh-group">
          {data.map((p) => (
            <div key={p.id} className="dh-row" style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14.5, fontWeight: 500 }}>
                  {p.amount_stars > 0
                    ? `${p.amount_stars} Stars`
                    : PROVIDER_LABEL[p.provider] ?? p.provider}
                  {p.coupon_code ? ` · ${p.coupon_code}` : ""}
                </div>
                <div className="dh-meta" style={{ marginTop: 4 }}>
                  {new Date(p.created_at).toLocaleDateString("de-DE", {
                    day: "2-digit",
                    month: "long",
                    year: "numeric",
                  })}
                  {p.amount_eur > 0 ? ` · ${p.amount_eur.toFixed(2)} €` : ""}
                </div>
              </div>
              <span
                className="dh-meta"
                style={{ alignSelf: "center", color: p.refunded ? "var(--dh-q-steal)" : undefined }}
              >
                {p.refunded
                  ? "erstattet"
                  : p.is_renewal
                    ? "Verlängerung"
                    : p.status === "granted"
                      ? "geschenkt"
                      : "bezahlt"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// --- Page --------------------------------------------------------------------------------
export function MiniApp() {
  const sdkReady = useTelegramSdk();
  const [tab, setTab] = useState<Tab>("deals");
  // Bumped whenever an action changes the account (e.g. a cancellation), so the
  // header pill and the Konto tab show the new state without a reload.
  const [meVersion, setMeVersion] = useState(0);
  const me = useLoad<Me>(() => webapp.me(), [sdkReady, meVersion]);

  return (
    <div className="dh-app" style={{ paddingBottom: 64 }}>
      <header className="dh-header">
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span className="dh-wordmark">Deal Hunter</span>
          {me.data && <span className="dh-pill">{me.data.entitlements.label}</span>}
        </div>
        {me.data && (
          <span className="dh-meta" style={{ fontSize: 12.5 }}>
            {me.data.name}
          </span>
        )}
      </header>

      <main className="dh-main">
        {me.error && (
          <ErrorNote text={`${me.error} — diese Seite läuft nur in Telegram, über das Menü des Bots.`} />
        )}
        {tab === "deals" && <DealsTab />}
        {tab === "rules" && <RulesTab />}
        {tab === "flips" && <FlipsTab />}
        {tab === "account" && (
          <AccountTab me={me.data} onChanged={() => setMeVersion((v) => v + 1)} />
        )}
      </main>

      <nav className="dh-tabbar">
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            data-active={tab === id ? 1 : 0}
            onClick={() => {
              haptic();
              setTab(id);
            }}
          >
            <Icon size={21} />
            {label}
          </button>
        ))}
      </nav>
    </div>
  );
}
