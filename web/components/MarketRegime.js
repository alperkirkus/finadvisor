"use client";
import { useEffect, useState } from "react";

const pct = (x, d = 0) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const DATE = (s) => s && new Date(s + "T12:00:00").toLocaleDateString("tr-TR",
  { day: "numeric", month: "long", year: "numeric" });

/* The one layer the portfolio backtest supported: S&P 500 against its
   200-day average, read at month end as the tested rule does. */
export default function MarketRegime({ compact = false }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    fetch("/api/market")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setD)
      .catch(() => setErr(true));
  }, []);

  if (err) return compact ? null : <div className="micro">Piyasa durumu alınamadı.</div>;
  if (!d) return null;

  const on = d.signal === "risk_on";
  const tone = on ? "good" : "critical";
  const label = on ? "Risk açık" : "Risk kapalı";
  const crossed = d.above_now !== on;

  if (compact) {
    return (
      <div className="small" style={{ marginTop: 6 }}>
        <span className={`state s-${tone}`}><span className="dot" />Piyasa: {label}</span>
        <span className="dim"> · S&P 500, 200 günlük ortalamanın
          {on ? " üstünde" : " altında"} (ay sonu kuralı)</span>
      </div>
    );
  }

  const e = d.evidence;
  return (
    <div className="section">
      <div className="section-title">Piyasa durumu</div>
      <div className="group group-pad">
        <div className="row spread wrap">
          <span className={`headline s-${tone}`}>{label}</span>
          <span className="chip">{DATE(d.signal_date)} ay sonu</span>
        </div>
        <div className="small" style={{ marginTop: 8 }}>
          S&P 500 ay sonunda 200 günlük ortalamasının
          {` ${pct(Math.abs(d.signal_distance), 1).replace("+", "")} ${on ? "üstündeydi" : "altındaydı"}`}
          {d.signal_since && <> ({DATE(d.signal_since)} ay sonundan beri)</>}.
          Bugün {pct(Math.abs(d.distance), 1).replace("+", "")} {d.above_now ? "üstünde" : "altında"}
          {crossed && <> — ortalama bugün kesildi; kural ay sonu kapanışına bakar,
            sinyal ancak ay sonu da öyle kapanırsa değişir</>}.
        </div>
        <div className="small" style={{ marginTop: 10 }}>
          {on
            ? "Kural hisse tutmaya izin veriyor."
            : "Kural hisse yerine hazine bonosu gösteriyor. Şirket ne kadar iyi olursa olsun, geçmişte bu dönemler büyük düşüşlerin çoğunu içerdi."}
        </div>
        <hr className="rule" style={{ margin: "14px 0" }} />
        <div className="micro">
          Neden önemli: {e.window} arasında bu kurala uyan S&P 500 fonu yıllık
          %{(e.with_rule.cagr * 100).toFixed(1)} getiri, %{(e.with_rule.vol * 100).toFixed(0)} oynaklık,
          en kötü düşüş {pct(e.with_rule.maxdd)}; sürekli tutmak %{(e.index.cagr * 100).toFixed(1)},
          %{(e.index.vol * 100).toFixed(0)}, {pct(e.index.maxdd)}. 20 yılda {e.switches} geçiş.
          Getiriyi artırmaz, düşüşü azaltır. {e.note} Yatırım tavsiyesi değildir.
        </div>
      </div>
    </div>
  );
}
