"use client";

const TEST_LABELS = {
  roa_positive: "ROA pozitif", cfo_positive: "Nakit akışı pozitif",
  roa_improving: "ROA iyileşiyor", accruals_clean: "Nakit kârı aşıyor",
  leverage_falling: "Kaldıraç azalıyor", liquidity_rising: "Likidite artıyor",
  no_dilution: "Sulandırma yok", margin_expanding: "Brüt marj genişliyor",
  turnover_rising: "Devir hızı artıyor",
};

/* No score is handed over without its failure mode. All three misfire in
   documented ways, and the backtest confirmed one of them: Piotroski runs
   inverted among large caps, exactly as its calibration predicts. */
const CAVEATS = {
  piotroski: "Değişim skoru, seviye skoru değil. Küçük ve defter değeri yüksek şirketlerde kalibre edildi; büyük şirketlerde ayırt ediciliği düşük — bu projenin backtest'inde bu evrende ters yönde çalıştı.",
  altman_z: "1968'de imalat şirketlerinde kalibre edildi ve faiz karşılamayı hiç görmez. Varlık-ağır ama istikrarlı şirketlerde yapay düşük çıkar.",
  beneish_m: "Yanlış pozitif oranı yüksek: hızlı büyüme ve satın almalar skoru bayrağa iter. Dolandırıcılık kanıtı değildir.",
};

function Row({ title, value, unit, tone, glyph, state, detail, caveat }) {
  return (
    <div style={{ padding: "20px 0", borderBottom: "1px solid var(--hair)" }}>
      <div className="row spread" style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
        <span style={{ fontSize: 14.5 }}>{title}</span>
        <span className="row" style={{ gap: 12 }}>
          <span className="num" style={{ fontSize: 19 }}>
            {value}{unit && <span className="dim" style={{ fontSize: 13 }}>{unit}</span>}
          </span>
          <span className={`chip s-${tone}`}>
            <span className="g" aria-hidden="true">{glyph}</span>{state}
          </span>
        </span>
      </div>
      {detail && <div className="small" style={{ marginTop: 6 }}>{detail}</div>}
      <div className="micro" style={{ marginTop: 6 }}>{caveat}</div>
    </div>
  );
}

export default function Scores({ scores, notApplicable }) {
  const f = scores.piotroski, z = scores.altman_z, b = scores.beneish_m;
  const skipped = (notApplicable || []).filter((k) =>
    ["piotroski", "altman_z", "beneish_m"].includes(k));
  const failed = f
    ? Object.entries(f.tests).filter(([, v]) => v === 0).map(([k]) => TEST_LABELS[k] || k)
    : [];

  return (
    <div>
      {f && (
        <Row title="Piotroski F-Score" value={f.score} unit={` / ${f.max}`}
             tone={f.score >= 7 ? "good" : f.score >= 4 ? "warning" : "critical"}
             glyph={f.score >= 7 ? "▲" : f.score >= 4 ? "◆" : "▼"}
             state={f.score >= 7 ? "güçlü" : f.score >= 4 ? "karışık" : "zayıf"}
             detail={failed.length ? `Başarısız: ${failed.join(", ")}` : "Tüm testler geçti"}
             caveat={CAVEATS.piotroski} />
      )}
      {z && z.z_double_prime !== undefined && (
        <Row title="Altman Z''-Score" value={z.z_double_prime.toFixed(2)}
             tone={z.zone === "safe" ? "good" : z.zone === "grey" ? "warning" : "critical"}
             glyph={z.zone === "safe" ? "▲" : z.zone === "grey" ? "◆" : "▼"}
             state={z.zone === "safe" ? "güvenli" : z.zone === "grey" ? "gri bölge" : "sıkıntı"}
             detail="2.6 üstü güvenli · 1.1–2.6 gri · altı sıkıntı"
             caveat={CAVEATS.altman_z} />
      )}
      {b && (
        <Row title="Beneish M-Score" value={b.m_score.toFixed(2)}
             tone={b.flag ? "warning" : "good"} glyph={b.flag ? "◆" : "▲"}
             state={b.flag ? "bayrak" : "temiz"}
             detail={`Eşik −1.78 · ${b.components_used}/8 bileşen hesaplandı`}
             caveat={CAVEATS.beneish_m} />
      )}
      {skipped.length > 0 && (
        <div className="micro" style={{ marginTop: 16 }}>
          Bu sektörde uygulanamayan skorlar gösterilmiyor ({skipped.join(", ")}).
          Altman ve Piotroski finans dışı şirketlerde kalibre edilmiştir.
        </div>
      )}
    </div>
  );
}
