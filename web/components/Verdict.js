"use client";
import { useEffect, useState } from "react";

const VERDICTS = {
  "yatirim yapilabilir":      { tone: "good",     g: "▲", label: "Yatırım yapılabilir" },
  "iyi sirket, pahali fiyat": { tone: "warning",  g: "◆", label: "İyi şirket, pahalı fiyat" },
  "ucuz ama sorunlu":         { tone: "warning",  g: "◆", label: "Ucuz ama sorunlu" },
  "kosullu":                  { tone: "warning",  g: "◆", label: "Koşullu" },
  "yatirim yapilamaz":        { tone: "critical", g: "▼", label: "Yatırım yapılamaz" },
  "fiyatlanamaz":             { tone: "neutral",  g: "■", label: "Fiyatlanamaz" },
  "fiyat verisi yok":         { tone: "neutral",  g: "■", label: "Fiyat verisi yok" },
  "degerlendirilemez":        { tone: "neutral",  g: "■", label: "Değerlendirilemez" },
};
const SEVERITY = {
  yuksek: { tone: "critical", g: "▲", label: "yüksek" },
  orta:   { tone: "serious",  g: "◆", label: "orta" },
  dusuk:  { tone: "warning",  g: "▪", label: "düşük" },
};

const money = (v) =>
  v == null ? "—"
  : Math.abs(v) >= 1e12 ? (v / 1e12).toFixed(2) + " T$"
  : Math.abs(v) >= 1e9 ? (v / 1e9).toFixed(1) + " Mr$"
  : (v / 1e6).toFixed(0) + " M$";
const pct = (v, d = 1) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
const toneOf = (s) => (s == null ? "neutral" : s >= 60 ? "good" : s < 40 ? "critical" : "warning");

function Def({ k, v, note, tone }) {
  return (
    <div>
      <span className="k">{k}</span>
      {/* A block element inside a span is invalid nesting and React flags it
          during hydration, so the note is a block-level span instead. */}
      <span style={{ textAlign: "right" }}>
        <span className={`v ${tone ? "s-" + tone : ""}`} style={{ fontSize: 16 }}>{v}</span>
        {note && (
          <span className="micro" style={{ display: "block", marginTop: 1 }}>{note}</span>
        )}
      </span>
    </div>
  );
}

export function Fold({ title, count, children, open = false }) {
  return (
    <details className="fold" open={open}>
      <summary>
        {title}
        {count != null && <span className="count">{count}</span>}
      </summary>
      <div className="inner">{children}</div>
    </details>
  );
}

export default function Verdict({ ticker, company, children }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setD(null); setError(null);
    fetch(`/api/valuation/${ticker}`)
      .then((r) => r.json().then((j) => (r.ok ? setD(j) : setError(j.detail))))
      .catch((e) => setError(String(e)));
  }, [ticker]);

  const head = (
    <div className="top spread wrap" style={{ marginBottom: 30 }}>
      <div>
        <div className="label" style={{ marginBottom: 7 }}>{company.industry}</div>
        <div className="display">{company.name}</div>
      </div>
      <div className="num dim" style={{ fontSize: 14, paddingTop: 26 }}>{company.ticker}</div>
    </div>
  );

  if (error) return <>{head}<div className="body">{error}</div></>;
  if (!d) return <>{head}<div className="small dim">Fiyat ve değerleme alınıyor…</div></>;

  const w = d.verdict, v = d.valuation;
  const vd = VERDICTS[w.verdict] || VERDICTS["kosullu"];
  const cc = v?.cost_of_capital;
  const implied = v?.dcf?.implied_growth;
  const hist = v?.assumptions?.historical_fcf_growth;
  const nq = w.next_quarter;

  return (
    <>
      {head}

      {v && (
        <div style={{ marginBottom: 26 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "26px 54px", alignItems: "flex-end" }}>
            <div>
              <div className="label" style={{ marginBottom: 6 }}>şu anki fiyat</div>
              <div className="price">{v.quote.price.toFixed(2)}</div>
            </div>
            {v.fair_value?.base != null && (
              <div>
                <div className="label" style={{ marginBottom: 6 }}>olması gereken</div>
                <div className="row" style={{ gap: 14, alignItems: "baseline" }}>
                  <span className="price" style={{ fontSize: 34 }}>
                    {v.fair_value.base.toFixed(2)}
                  </span>
                  <span className={`num s-${
                    v.upside_to_fair > 0.15 ? "good"
                    : v.upside_to_fair < -0.15 ? "critical" : "warning"}`}
                        style={{ fontSize: 18 }}>
                    {v.upside_to_fair > 0 ? "+" : ""}{(v.upside_to_fair * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            )}
          </div>
          <div className="micro" style={{ marginTop: 12 }}>
            {v.quote.currency} · {v.quote.exchange} · {money(v.market_cap)} piyasa değeri
            {v.fair_value?.basis && <> · {v.fair_value.basis}</>}
          </div>
          {v.reversion?.window_note && (
            <div className="micro s-warning" style={{ marginTop: 8 }}>
              <span aria-hidden="true">◆ </span>{v.reversion.window_note}
            </div>
          )}
          {v.divergence && (
            <div className={`note ${v.divergence.level === "yuksek" ? "s-warning" : "s-neutral"}`}
                 style={{ marginTop: 16 }}>
              <div className="small">{v.divergence.note}</div>
            </div>
          )}
        </div>
      )}

      <div className={`headline state s-${vd.tone}`} style={{ marginBottom: 12 }}>
        <span className="g" aria-hidden="true">{vd.g}</span>{vd.label}
      </div>
      <div className="lead" style={{ marginBottom: 40, maxWidth: "58ch" }}>{w.rationale}</div>

      {/* The one part of the output with measured evidence behind it, kept
          separate from the framework score rather than folded into it. */}
      {w.measured_signals?.length > 0 && (
        <div style={{ marginBottom: 40 }}>
          <div className="label" style={{ marginBottom: 14 }}>Ölçülmüş sinyaller</div>
          {w.measured_signals.map((m) => (
            <div key={m.name} className={`note s-${m.tone}`} style={{ marginBottom: 18 }}>
              <div className="row" style={{ gap: 12, alignItems: "baseline" }}>
                <span style={{ color: "var(--ink)", fontSize: 15 }}>{m.name}</span>
                <span className="num" style={{ fontSize: 17 }}>{pct(m.value)}</span>
                <span className={`chip s-${m.tone}`}>{m.state}</span>
              </div>
              <div className="small" style={{ marginTop: 3 }}>{m.reading}</div>
              <div className="micro" style={{ marginTop: 5 }}>{m.evidence}</div>
            </div>
          ))}
        </div>
      )}

      {v && (
        <>
          <hr className="rule" />
          <div className="defs">
            <Def k="Adil değer aralığı"
                 v={v.fair_value ? `${v.fair_value.low} – ${v.fair_value.high}` : "—"}
                 note={v.fair_value ? `baz ${v.fair_value.base}` : "nakit akışı iskontosu uygulanamadı"} />
            <Def k="Güvenlik payı"
                 v={v.margin_of_safety == null ? "—" : pct(v.margin_of_safety, 0)}
                 tone={v.margin_of_safety == null ? null
                   : v.margin_of_safety > 0.15 ? "good"
                   : v.margin_of_safety < -0.15 ? "critical" : "warning"}
                 note="adil değere göre fiyat konumu" />
            <Def k="Fiyatın ima ettiği büyüme" v={pct(implied)}
                 tone={implied == null || hist == null ? null : hist >= implied ? "good" : "critical"}
                 note={hist == null ? null
                   : `şirketin geçmişi ${pct(hist)} — ${hist >= implied ? "karşılanabilir" : "bunun üstünde"}`} />
            <Def k="Sermaye maliyeti" v={pct(cc?.wacc, 2)}
                 note={cc?.beta ? `beta ${cc.beta}, ${cc.beta_months} ay regresyon` : cc?.method} />
          </div>
        </>
      )}

      <div style={{ marginTop: 44 }}>
        {w.caveats.length > 0 && (
          <Fold title="Bu sonucu okurken" count={w.caveats.length}>
            <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
              {w.caveats.map((f, i) => {
                const s = SEVERITY[f.severity] || SEVERITY.orta;
                return (
                  <div key={i} className={`note s-${s.tone}`}>
                    <div className="chip" style={{ marginBottom: 3 }}>
                      <span className="g" aria-hidden="true">{s.g}</span>
                      <span style={{ color: "var(--ink)" }}>{f.signal}</span>
                    </div>
                    <div className="small">{f.evidence}</div>
                    {f.benign_explanation && (
                      <div className="micro" style={{ marginTop: 5 }}>
                        Zararsız alternatif: {f.benign_explanation}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Fold>
        )}

        <Fold title="Sütunlar">
          <div className="defs">
            {w.pillars.map((p) => (
              <div key={p.name} style={{ display: "block", padding: "15px 0" }}>
                <div className={`spread s-${toneOf(p.score)}`} style={{ display: "flex", marginBottom: 7 }}>
                  <span style={{ color: "var(--ink)", fontSize: 14.5 }}>{p.name}</span>
                  <span className="num" style={{ fontSize: 14 }}>
                    {p.score == null ? <span className="dim">{p.band}</span> : p.score.toFixed(0)}
                  </span>
                </div>
                <div className={`meter s-${toneOf(p.score)}`}><i style={{ width: `${p.score ?? 0}%` }} /></div>
                <div className="micro" style={{ marginTop: 9 }}>{p.reasons.join(" · ")}</div>
              </div>
            ))}
          </div>
        </Fold>

        {v?.reversion && (
          <Fold title="Adil değer nasıl bulundu">
            <div className="small" style={{ marginBottom: 18 }}>
              Manşetteki sayı, şirketin <strong>kendi tarihsel EV/FCF
              medyanına</strong> dönüşünden geliyor. Bu yöntemin iskonto oranı,
              terminal değer veya büyüme tahmini yoktur — çünkü tek bir iskonto
              oranı seçimi sonucu üçte bir oynatabiliyor, ve yüksek betalı
              büyüme şirketlerinde aynı özelliği iki kez cezalandırıyor.
            </div>
            <table>
              <tbody>
                <tr><td>Şu anki EV / FCF</td>
                    <td className="r">{v.reversion.current_ev_fcf.toFixed(1)}×</td></tr>
                <tr><td>Kendi tarihsel medyanı</td>
                    <td className="r">{v.reversion.median_ev_fcf.toFixed(1)}×</td></tr>
                <tr><td>Medyana göre prim</td>
                    <td className={`r s-${v.reversion.premium_to_own_history > 0.25 ? "critical"
                      : v.reversion.premium_to_own_history < -0.15 ? "good" : "warning"}`}>
                      {v.reversion.premium_to_own_history > 0 ? "+" : ""}
                      {(v.reversion.premium_to_own_history * 100).toFixed(0)}%</td></tr>
                <tr><td>Çeyrek yüzdelik aralığı (25–75)</td>
                    <td className="r">{v.reversion.low.toFixed(2)} – {v.reversion.high.toFixed(2)}</td></tr>
                <tr><td>Referans pencere</td>
                    <td className="r">{v.reversion.years} yıl · {v.reversion.observations} çeyrek</td></tr>
              </tbody>
            </table>
            {v.dcf_upside != null && (
              <div className="micro" style={{ marginTop: 16 }}>
                Çapraz kontrol: iskonto edilmiş nakit akışı yöntemi
                {" "}{v.dcf_fair_value?.base?.toFixed(2)} veriyor
                ({v.dcf_upside > 0 ? "+" : ""}{(v.dcf_upside * 100).toFixed(0)}%).
                İki yöntem ayrışıyorsa sonuç varsayıma bağlı demektir.
              </div>
            )}
          </Fold>
        )}

        {v?.sensitivity && (
          <Fold title="İskonto yöntemi duyarlılığı">
            <div className="small" style={{ marginBottom: 16 }}>
              Çapraz kontrol yöntemi. Terminal değer, iskonto oranı ile büyüme
              arasındaki farka hipersensitiftir; ızgara varsayımların sonucu ne
              kadar oynattığını gösterir.
            </div>
            <table>
              <thead>
                <tr>
                  <th>İskonto ↓ / büyüme →</th>
                  {v.sensitivity.growth.map((g, i) => (
                    <th key={i} className="r">{(g * 100).toFixed(1)}%</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {v.sensitivity.wacc.map((r, i) => (
                  <tr key={i}>
                    <td className="num">{(r * 100).toFixed(2)}%</td>
                    {v.sensitivity.grid[i].map((cell, j) => (
                      <td key={j} className="r"
                          style={v.sensitivity.base_cell?.[0] === i
                                 && v.sensitivity.base_cell?.[1] === j
                                 ? { color: "var(--ink)", fontWeight: 500 } : undefined}>
                        {cell == null ? "—" : cell.toFixed(2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="micro" style={{ marginTop: 14 }}>
              Kalın hücre baz senaryodur. Şu anki fiyat {v.quote.price.toFixed(2)}.
            </div>
          </Fold>
        )}

        {v && (
          <Fold title="Çarpanlar">
            <table>
              <tbody>
                {[["pe", "F/K"], ["p_fcf", "Fiyat / serbest nakit"],
                  ["ev_ebitda", "EV / FAVÖK"], ["ev_sales", "EV / satış"],
                  ["fcf_yield", "Serbest nakit getirisi"]].map(([k, label]) => (
                  <tr key={k}>
                    <td>{label}</td>
                    <td className="r">
                      {v.multiples[k] == null ? <span className="dim">n/a</span>
                        : k.endsWith("yield") ? pct(v.multiples[k])
                        : v.multiples[k].toFixed(1) + "×"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Fold>
        )}

        {nq.available && (
          <Fold title="Gelecek çeyrek projeksiyonu">
            <table>
              <tbody>
                <tr><td>Gelir</td><td className="r">
                  {money(nq.revenue_range[0])} – {money(nq.revenue_range[1])}</td></tr>
                {nq.operating_income_range && (
                  <tr><td>Faaliyet kârı</td><td className="r">
                    {money(nq.operating_income_range[0])} – {money(nq.operating_income_range[1])}</td></tr>
                )}
                {nq.fcf_range && (
                  <tr><td>Serbest nakit</td><td className="r">
                    {money(nq.fcf_range[0])} – {money(nq.fcf_range[1])}</td></tr>
                )}
              </tbody>
            </table>
            <div className="micro" style={{ marginTop: 14 }}>
              {nq.basis}. {nq.margin_assumption} {nq.caveats.join(" ")}
            </div>
          </Fold>
        )}

        {children}

        {v && (
          <Fold title="Varsayımlar ve kaynaklar">
            <div className="micro" style={{ lineHeight: 1.8 }}>
              İskonto oranı %{(cc.wacc * 100).toFixed(2)}
              {cc.beta && ` — CAPM: risksiz oran %${(cc.risk_free * 100).toFixed(2)},
                beta ${cc.beta}${cc.beta_floored ? ` (${cc.beta_used} tabanına yükseltildi)` : ""},
                risk primi %${(cc.equity_risk_premium * 100).toFixed(1)},
                özsermaye maliyeti %${(cc.cost_of_equity * 100).toFixed(2)},
                borç maliyeti %${(cc.cost_of_debt * 100).toFixed(2)},
                özsermaye ağırlığı %${(cc.equity_weight * 100).toFixed(0)}`}.
              {" "}Terminal büyüme %{(v.assumptions.terminal_growth * 100).toFixed(1)},
              ufuk {v.assumptions.horizon_years} yıl.
              {" "}Nakit akışı tabanı: {v.assumptions.cash_flow_base}.
              {" "}Büyüme: {v.assumptions.growth_basis},
              %{(v.assumptions.historical_fcf_growth * 100).toFixed(1)} (−%5 ile +%15 arasına kısıtlı).
              {" "}{v.assumptions.note}
              {" "}Hisse sayısı {(v.shares_outstanding / 1e9).toFixed(3)} milyar,
              SEC kapak sayfasından. Fiyat: {v.quote.source}.
              {" "}Güven: {w.confidence.level} — {w.confidence.rationale}
            </div>
            <div className="micro" style={{ marginTop: 16 }}>{w.basis}</div>
            <div className="micro" style={{ marginTop: 12 }}>{w.disclaimer}</div>
          </Fold>
        )}
      </div>
    </>
  );
}
