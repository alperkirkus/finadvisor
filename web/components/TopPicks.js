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
const PAGE = 10;

export default function TopPicks({ onPick }) {
  const [d, setD] = useState(null);
  const [more, setMore] = useState(false);

  useEffect(() => {
    fetch(`/api/ranking?limit=${PAGE}`)
      .then((r) => r.json())
      .then(setD)
      .catch(() => setD({ rows: [] }));
  }, []);

  function showMore() {
    setMore(true);
    fetch(`/api/ranking?limit=${PAGE}&offset=${d.rows.length}`)
      .then((r) => r.json())
      .then((n) => setD((cur) => ({ ...cur, rows: [...cur.rows, ...n.rows] })))
      .finally(() => setMore(false));
  }

  if (!d) return <div className="small dim">Sıralama yükleniyor…</div>;
  if (!d.rows.length) {
    return <div className="micro" style={{ marginTop: 40 }}>{d.note || "Sıralama yok."}</div>;
  }

  return (
    <div className="section">
      <div className="section-title">Algoritmaya göre sıralama</div>
      <div className="group">
        {d.rows.map((r, i) => {
          const t = TONE[r.verdict] || TONE["kosullu"];
          return (
            <button key={r.ticker} className="listbtn" onClick={() => onPick(r.ticker)}>
              <span className="num dim" style={{ width: 28, fontSize: 14 }}>{i + 1}</span>
              <span style={{ flex: 1 }}>
                <span className="row" style={{ gap: 8, alignItems: "baseline" }}>
                  <span style={{ fontWeight: 600, fontSize: 16 }}>{r.ticker}</span>
                  <span className="dim" style={{ fontSize: 14, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
                </span>
                <span className={`chip s-${t.tone}`} style={{ marginTop: 5 }}>{t.label}</span>
              </span>
              <span style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                <span className="num" style={{ display: "block", fontSize: 16 }}>
                  {r.price != null ? r.price.toFixed(2) : "—"}
                </span>
                {r.upside != null && (
                  <span className={`num s-${r.upside > 0.10 ? "good"
                    : r.upside < -0.10 ? "critical" : "neutral"}`}
                        style={{ display: "block", fontSize: 13 }}>
                    {r.upside > 0 ? "+" : ""}{(r.upside * 100).toFixed(0)}%
                  </span>
                )}
              </span>
              <span className="chev" aria-hidden="true">›</span>
            </button>
          );
        })}
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
        {d.universe_size} şirket arasından, şirket sayfasıyla aynı kurallarla
        sıralandı ({d.generated_at?.slice(0, 10)}). Genel puan: işletme %60,
        değerleme %40. Bloke edilen şirketler listenin sonuna gider.
      </div>
    </div>
  );
}
