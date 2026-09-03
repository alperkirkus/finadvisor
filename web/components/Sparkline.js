"use client";
import { useRef, useState } from "react";

const W = 300, H = 46, PAD = 3;

/* One series, no legend -- the caption above names it. A crosshair and
   tooltip ship by default: a plotted line the reader can point at should
   answer "what value, when" without a lookup elsewhere. */
export default function Sparkline({ series, formatValue, tone = "accent" }) {
  const [hover, setHover] = useState(null);
  const box = useRef(null);
  const points = (series || []).filter((p) => p[1] !== null && p[1] !== undefined);

  if (points.length < 2) {
    return <div className="t-micro" style={{ height: H, display: "flex", alignItems: "center" }}>
      yeterli dönem yok
    </div>;
  }

  const values = points.map((p) => p[1]);
  let lo = Math.min(...values), hi = Math.max(...values);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.15;
  lo -= pad; hi += pad;

  const x = (i) => PAD + (i * (W - PAD * 2)) / (points.length - 1);
  const y = (v) => 4 + (1 - (v - lo) / (hi - lo)) * (H - 8);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const last = points.length - 1;
  const at = hover === null ? last : hover;
  const stroke = tone === "accent" ? "var(--accent)" : `var(--${tone})`;

  function onMove(e) {
    const r = box.current.getBoundingClientRect();
    const rel = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((rel - PAD) / (W - PAD * 2)) * (points.length - 1));
    setHover(Math.max(0, Math.min(last, i)));
  }

  return (
    <div ref={box} style={{ position: "relative", color: stroke }}
         onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none"
           role="img" aria-label={`${points.length} dönem, son ${formatValue(points[last][1])}`}>
        {lo < 0 && hi > 0 && (
          <line x1={PAD} x2={W - PAD} y1={y(0)} y2={y(0)}
                stroke="var(--line-strong)" strokeWidth="0.6" strokeDasharray="2 3"
                vectorEffect="non-scaling-stroke" />
        )}
        <path d={line} fill="none" stroke="currentColor" strokeWidth="1.6"
              strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {hover !== null && (
          <line x1={x(at)} x2={x(at)} y1={0} y2={H}
                stroke="var(--line-strong)" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
        )}
        <circle cx={x(at)} cy={y(points[at][1])} r="2.4" fill="currentColor"
                stroke="var(--surface)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
      {hover !== null && (
        <div className="tip" style={{
          left: `${Math.min(Math.max((x(at) / W) * 100, 6), 94)}%`,
          top: -6, transform: "translate(-50%, -100%)",
        }}>
          {formatValue(points[at][1])} · {points[at][0].slice(0, 7)}
        </div>
      )}
    </div>
  );
}
