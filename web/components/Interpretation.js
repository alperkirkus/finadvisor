"use client";
import { useEffect, useState } from "react";
import { meta, format } from "../lib/metrics";

/* The verdict panel already carries the red flags and the confidence note,
   so this covers what it does not: which metrics stand out either way, and
   what would change the read next quarter. */
export default function Interpretation({ ticker }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setD(null); setError(null);
    fetch(`/api/interpret/${ticker}`)
      .then((r) => r.json().then((j) => (r.ok ? setD(j.interpretation) : setError(j.detail))))
      .catch((e) => setError(String(e)));
  }, [ticker]);

  if (error) return <div className="body">{error}</div>;
  if (!d) return <div className="small dim">Değerlendiriliyor…</div>;

  return (
    <div>
      <div className="label" style={{ marginBottom: 10 }}>Eşiği aşanlar</div>
      <Side items={d.strengths} tone="good" glyph="▲" empty="Yok" />

      <div className="label" style={{ margin: "26px 0 10px" }}>Eşiğin altındakiler</div>
      <Side items={d.concerns} tone="critical" glyph="▼" empty="Yok" />

      {d.sector_note && (
        <div className="micro" style={{ marginTop: 22 }}>{d.sector_note}</div>
      )}

      {d.watch_items.length > 0 && (
        <>
          <div className="label" style={{ margin: "34px 0 10px" }}>
            Önümüzdeki çeyrekte izlenecekler
          </div>
          <table>
            <thead>
              <tr><th>Metrik</th><th className="r">Şimdi</th><th>Doğrular</th><th>Çürütür</th></tr>
            </thead>
            <tbody>
              {d.watch_items.map((w) => (
                <tr key={w.metric}>
                  <td style={{ fontSize: 14 }}>{meta(w.metric).label}</td>
                  <td className="r">{format(w.metric, w.current)}</td>
                  <td className="micro">{w.confirms_if}</td>
                  <td className="micro">{w.refutes_if}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <div className="micro" style={{ marginTop: 20 }}>{d.method}</div>
    </div>
  );
}

function Side({ items, tone, glyph, empty }) {
  if (!items.length) return <div className="small dim">{empty}</div>;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 22px" }}>
      {items.map((v) => (
        <span key={v.metric} className={`chip s-${tone}`}>
          <span className="g" aria-hidden="true">{glyph}</span>
          <span style={{ color: "var(--ink-2)" }}>{meta(v.metric).label}</span>
          <span className="num" style={{ fontSize: 12.5, color: "var(--ink)" }}>
            {format(v.metric, v.value)}
          </span>
          {v.sector_adjusted && <span className="dim" title="Eşik sektöre göre ayarlandı">*</span>}
        </span>
      ))}
    </div>
  );
}
