"use client";
import { useCallback, useEffect, useRef, useState } from "react";

const TONE = {
  "yatirim yapilabilir": { tone: "good", g: "▲", label: "Yatırım yapılabilir" },
  "ucuz ama sorunlu": { tone: "warning", g: "◆", label: "Ucuz ama sorunlu" },
  "kosullu": { tone: "warning", g: "◆", label: "Koşullu" },
  "iyi sirket, pahali fiyat": { tone: "warning", g: "◆", label: "İyi şirket, pahalı fiyat" },
  "fiyatlanamaz": { tone: "neutral", g: "■", label: "Fiyatlanamaz" },
  "fiyat verisi yok": { tone: "neutral", g: "■", label: "Fiyat verisi yok" },
  "degerlendirilemez": { tone: "neutral", g: "■", label: "Değerlendirilemez" },
  "yatirim yapilamaz": { tone: "critical", g: "▼", label: "Yatırım yapılamaz" },
};
const verdictOf = (v) => TONE[v] || TONE["kosullu"];

/* The same ordering the single-company view would produce, surfaced as a
   list. A screen ranked by a different rule than the one it explains would
   be a second, hidden model. */
const PAGE = 10;
const LIVE_BATCH = 10;

const signed = (v, d = 0) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;
const day = (iso) =>
  new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });

function Upside({ v, muted }) {
  if (v == null) return null;
  const tone = v > 0.10 ? "good" : v < -0.10 ? "critical" : "neutral";
  const word = v > 0.10 ? "ucuz" : v < -0.10 ? "pahalı" : "yakın";
  return (
    <span className={`num ${muted ? "dim" : "s-" + tone}`} style={{ fontSize: 13 }}>
      {signed(v)}{muted ? "" : ` ${word}`}
    </span>
  );
}

function Filter({ label, options, value, onChange }) {
  if (!options?.length) return null;
  return (
    <div className="filters" role="group" aria-label={label}>
      <span className="dim">{label}</span>
      <button className={`seg ${value == null ? "on" : ""}`} aria-pressed={value == null}
              onClick={() => onChange(null)}>
        Tümü
      </button>
      {options.map((o) => (
        <button key={o.key} className={`seg ${value === o.key ? "on" : ""}`}
                aria-pressed={value === o.key} onClick={() => onChange(o.key)}>
          {o.label} <span className="num dim">{o.count}</span>
        </button>
      ))}
    </div>
  );
}

export default function TopPicks({ onPick, active = true }) {
  const [d, setD] = useState(null);
  const [wait, setWait] = useState(null);
  const [risk, setRisk] = useState(null);
  const [more, setMore] = useState(false);
  const [filters, setFilters] = useState(false);
  const [live, setLive] = useState({});
  const request = useRef(0);

  // Today's price, fair value and verdict for the rows on screen, from the
  // same computation the company page runs. A ticker that cannot be read is
  // marked as such; the stored value of the run is never shown in its place.
  const loadLive = useCallback(async (tickers) => {
    for (let i = 0; i < tickers.length; i += LIVE_BATCH) {
      const chunk = tickers.slice(i, i + LIVE_BATCH);
      let rows;
      try {
        const r = await fetch(`/api/live?tickers=${chunk.map(encodeURIComponent).join(",")}`);
        if (!r.ok) throw new Error(String(r.status));
        rows = (await r.json()).rows;
      } catch {
        rows = Object.fromEntries(chunk.map((t) => [t, { error: "alınamadı" }]));
      }
      setLive((cur) => ({ ...cur, ...rows }));
    }
  }, []);

  const loadPage = useCallback(async (offset, filters) => {
    const id = ++request.current;
    const q = new URLSearchParams({ limit: PAGE, offset });
    for (const [k, v] of Object.entries(filters)) if (v) q.set(k, v);
    const r = await fetch(`/api/ranking?${q}`);
    const n = await r.json();
    if (!r.ok) throw new Error(n.detail || String(r.status));
    if (id !== request.current) return;
    setD((cur) => (offset ? { ...n, rows: [...cur.rows, ...n.rows] } : n));
    loadLive(n.rows.map((x) => x.ticker));
  }, [loadLive]);

  useEffect(() => {
    loadPage(0, { wait, risk }).catch(() => setD({ rows: [] }));
  }, [loadPage, wait, risk]);

  // Coming back from a company page: the list is still open where it was
  // left, and its prices are read again so they match the page just seen.
  const tickers = d?.rows.map((r) => r.ticker).join(",") || "";
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current && tickers) loadLive(tickers.split(","));
    wasActive.current = active;
  }, [active, tickers, loadLive]);

  function showMore() {
    setMore(true);
    loadPage(d.rows.length, { wait, risk }).catch(() => {}).finally(() => setMore(false));
  }

  if (!d) return <div className="small dim">Sıralama yükleniyor…</div>;
  if (!d.rows.length && !wait && !risk) {
    return <div className="micro" style={{ marginTop: 40 }}>{d.note || "Sıralama yok."}</div>;
  }

  const hasPrevious = d.previous_generated_at != null;

  return (
    <div className="section">
      <div className="section-title">Algoritmaya göre sıralama</div>

      <button className="link" onClick={() => setFilters(!filters)} style={{ margin: "0 22px 10px" }}>
        {filters ? "Süzgeçleri gizle" : `Listeyi süz${risk || wait ? " (süzgeç etkin)" : ""} ›`}
      </button>
      {filters && (
        <div className="fade">
          <Filter label="Düşüş riski" options={d.risk_options} value={risk} onChange={setRisk} />
          <div className="micro" style={{ margin: "-6px 22px 12px" }}>
            Fiyatı ne kadar oynak: benzer oynaklıktaki şirketlerin geçmişte bir yılda sert düşme sıklığı.
          </div>
          <Filter label="Beklenen süre" options={d.wait_options} value={wait} onChange={setWait} />
          <div className="micro" style={{ margin: "-6px 22px 12px" }}>
            Fiyatın hesaplanan değere yaklaşması için beklenen süre. "Yakın": fiyat zaten değerine yakın.
          </div>
        </div>
      )}

      <div className="group">
        <div className="listhead">
          <span style={{ flex: 1 }}>Şirket</span>
          <span className="col-now">Şimdi</span>
          {hasPrevious && (
            <span className="col-prev">Önceki çalıştırma · {day(d.previous_generated_at)}</span>
          )}
        </div>
        {d.rows.map((r) => {
          const now = live[r.ticker];
          const priced = now && now.price != null;
          const prev = r.previous;
          const t = verdictOf(now?.verdict || r.verdict);
          const since = priced && prev?.price ? now.price / prev.price - 1 : null;
          const changed = now?.verdict && prev?.verdict && now.verdict !== prev.verdict;
          return (
            <button key={r.ticker} className="listbtn" onClick={() => onPick(r.ticker)}>
              <span className="num dim" style={{ width: 28, fontSize: 14 }}>{r.rank}</span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span className="row" style={{ gap: 8, alignItems: "baseline" }}>
                  <span style={{ fontWeight: 600, fontSize: 16 }}>{r.ticker}</span>
                  <span className="dim" style={{ fontSize: 14, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
                </span>
                <span className={`chip s-${t.tone}`} style={{ marginTop: 5 }}>{t.label}</span>
                {(now?.risk || r.risk) === "q5" && (
                  <span className="chip s-critical" style={{ marginTop: 5, marginLeft: 6 }}>
                    Düşüş riski çok yüksek
                  </span>
                )}
              </span>
              <span className="col-now">
                {now == null ? <span className="dim">…</span>
                  : !priced ? <span className="dim" title={now.error || "fiyat yok"}>—</span>
                  : (
                    <>
                      <span className="num" style={{ display: "block", fontSize: 16 }}>
                        {now.price.toFixed(2)}
                      </span>
                      <Upside v={now.upside} />
                    </>
                  )}
              </span>
              {hasPrevious && (
                <span className="col-prev">
                  {prev?.price == null ? <span className="dim">—</span> : (
                    <>
                      <span className="num dim" style={{ display: "block", fontSize: 13 }}>
                        {prev.price.toFixed(2)}
                        {prev.upside != null && <> · <Upside v={prev.upside} muted /></>}
                      </span>
                      {since != null && (
                        <span className={`num s-${since > 0.005 ? "good"
                          : since < -0.005 ? "critical" : "neutral"}`}
                              style={{ display: "block", fontSize: 13 }}>
                          o günden {signed(since, 1)}
                        </span>
                      )}
                      {changed && (
                        <span className="dim" style={{ display: "block", fontSize: 12 }}>
                          {verdictOf(prev.verdict).label}
                        </span>
                      )}
                    </>
                  )}
                </span>
              )}
              <span className="chev" aria-hidden="true">›</span>
            </button>
          );
        })}
        {!d.rows.length && (
          <div className="group-pad small dim">Bu iki filtreye birlikte uyan şirket yok.</div>
        )}
        {d.total > d.rows.length && (
          <button className="listbtn more" onClick={showMore} disabled={more}>
            {more ? "Yükleniyor…" : `Sonraki ${Math.min(PAGE, d.total - d.rows.length)} şirketi göster`}
            <span className="dim" style={{ marginLeft: "auto", fontSize: 14 }}>
              {d.rows.length} / {d.total}
            </span>
          </button>
        )}
      </div>
      <div className="section-foot">
        {d.universe_size} şirket, şirket sayfasıyla aynı kurallarla{" "}
        {d.generated_at ? day(d.generated_at) : "—"} tarihinde sıralandı. "Şimdi"
        sütunu şu anki fiyatla, şirket sayfasındaki hesabın aynısıdır.
        {hasPrevious && (
          <> "Önceki çalıştırma" o günkü fiyatı ve adil değere uzaklığı,
          altında fiyatın o günden bugüne değişimini gösterir; karar
          değiştiyse o günkü karar da yazar.</>
        )}
        {" "}Genel puan: işletme %60, değerleme %40. Bloke edilen şirketler
        listenin sonuna gider.
      </div>
    </div>
  );
}
