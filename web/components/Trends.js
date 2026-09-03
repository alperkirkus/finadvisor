"use client";
import Sparkline from "./Sparkline";
import { meta, format, directionStatus } from "../lib/metrics";

const GLYPH = { good: "▲", critical: "▼", neutral: "·" };

/* One metric per row, one series per chart, all in the same accent: identity
   comes from the label beside it, so there is no legend and no per-series
   hue to decode. */
export default function Trends({ trends }) {
  const keys = Object.keys(trends)
    .sort((a, b) => meta(a).label.localeCompare(meta(b).label, "tr"));

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {keys.map((key) => {
        const t = trends[key];
        const st = directionStatus(t.direction);
        const latest = t.series[t.series.length - 1][1];
        return (
          <div key={key} style={{
            display: "grid", gridTemplateColumns: "1fr 150px", gap: 24,
            alignItems: "center", padding: "16px 0",
            borderBottom: "1px solid var(--hair)",
          }}>
            <div>
              <div style={{ fontSize: 14.5 }}>{meta(key).label}</div>
              <div className="row" style={{ gap: 12, marginTop: 2 }}>
                <span className="num" style={{ fontSize: 17 }}>{format(key, latest)}</span>
                <span className={`chip s-${st.role}`}>
                  <span className="g" aria-hidden="true">{GLYPH[st.role]}</span>{st.label}
                </span>
              </div>
              <div className="micro" style={{ marginTop: 2 }}>
                {format(key, t.prior_4q_avg)} → {format(key, t.recent_4q_avg)}
                {t.polarity === "lower_is_better" && " · düşmesi iyi"}
              </div>
            </div>
            <Sparkline series={t.series} formatValue={(v) => format(key, v)} />
          </div>
        );
      })}
    </div>
  );
}
