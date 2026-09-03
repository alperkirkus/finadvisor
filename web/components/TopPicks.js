"use client";
import { useEffect, useState } from "react";

const TONE = {
  "yatirim yapilabilir": { tone: "good", g: "▲", label: "Yatırım yapılabilir" },
  "ucuz ama sorunlu": { tone: "warning", g: "◆", label: "Ucuz ama sorunlu" },
  "kosullu": { tone: "warning", g: "◆", label: "Koşullu" },
  "iyi sirket, pahali fiyat": { tone: "warning", g: "◆", label: "İyi şirket, pahalı fiyat" },
  "fiyatlanamaz": { tone: "neutral", g: "■", label: "Fiyatlanamaz" },
  "yatirim yapilamaz": { tone: "critical", g: "▼", label: "Yatırım yapılamaz" },
};

/* The same ordering the single-company view would produce, surfaced as a
   list. A screen ranked by a different rule than the one it explains would
   be a second, hidden model. */
export default function TopPicks({ onPick }) {
  const [d, setD] = useState(null);

  useEffect(() => {
    fetch("/api/ranking?limit=10")
      .then((r) => r.json())
      .then(setD)
      .catch(() => setD({ rows: [] }));
  }, []);

  if (!d) return <div className="small dim" style={{ marginTop: 40 }}>Sıralama yükleniyor…</div>;
  if (!d.rows.length) {
    return <div className="micro" style={{ marginTop: 40 }}>{d.note || "Sıralama yok."}</div>;
  }

  return (
    <div style={{ marginTop: 54 }}>
      <div className="label" style={{ marginBottom: 4 }}>Algoritmaya göre en iyi 10</div>
      <div className="micro" style={{ marginBottom: 20 }}>
        {d.universe_size} şirket arasından, tek şirket sayfasıyla aynı kurallarla sıralandı.
      </div>

      <div>
        {d.rows.map((r, i) => {
          const t = TONE[r.verdict] || TONE["kosullu"];
          return (
            <button
              key={r.ticker}
              onClick={() => onPick(r.ticker)}
              style={{
                display: "grid", gridTemplateColumns: "26px 1fr auto", gap: 16,
                width: "100%", textAlign: "left", alignItems: "baseline",
                padding: "15px 0", borderBottom: "1px solid var(--hair)",
                color: "var(--ink)",
              }}>
              <span className="num dim" style={{ fontSize: 12.5 }}>{i + 1}</span>

              <span>
                <span className="row" style={{ gap: 10, alignItems: "baseline" }}>
                  <span className="num" style={{ fontSize: 14 }}>{r.ticker}</span>
                  <span style={{ fontSize: 14.5 }}>{r.name}</span>
                </span>
                <span className={`chip s-${t.tone}`} style={{ marginTop: 2 }}>
                  <span className="g" aria-hidden="true">{t.g}</span>{t.label}
                </span>
                <span className="micro" style={{ display: "block", marginTop: 2 }}>
                  işletme {r.business_score ?? "—"} · değerleme {r.valuation_score ?? "—"} · {r.industry}
                </span>
                {(r.divergence === "yuksek" || r.window_quality === "cok kisa") && (
                  <span className="micro s-warning" style={{ display: "block", marginTop: 2 }}>
                    <span aria-hidden="true">◆ </span>
                    {r.divergence === "yuksek"
                      ? "değerleme model ile piyasa arasında büyük ayrışmaya dayanıyor"
                      : "referans pencere çok kısa"}
                  </span>
                )}
              </span>

              <span style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                <span className="num" style={{ fontSize: 15 }}>
                  {r.price != null ? r.price.toFixed(2) : "—"}
                </span>
                {r.upside != null && (
                  <span className={`num s-${r.upside > 0.15 ? "good"
                    : r.upside < -0.15 ? "critical" : "warning"}`}
                        style={{ display: "block", fontSize: 12.5 }}>
                    {r.upside > 0 ? "+" : ""}{(r.upside * 100).toFixed(0)}%
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div className="micro" style={{ marginTop: 16 }}>
        Sıralama {d.generated_at?.slice(0, 10)} tarihinde hesaplandı. Genel puan =
        işletme %60 + değerleme %40. Bloke edilen şirketler puanı ne olursa olsun
        listenin sonuna gider; değerlemesi model-piyasa ayrışmasına dayananlar da
        aynı sonuç sınıfı içinde geriye alınır.
      </div>
    </div>
  );
}
