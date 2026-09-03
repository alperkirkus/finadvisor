"use client";
import { useEffect, useRef, useState } from "react";

export default function Search({ onPick, busy }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState([]);
  const [total, setTotal] = useState(0);
  const [browsing, setBrowsing] = useState(false);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const timer = useRef(null);

  // An empty field still queries: the endpoint answers with the head of the
  // filer list, so focusing the input shows what can be looked at instead of
  // an empty box the user has to guess at.
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(q.trim())}&limit=60`);
        const d = await r.json();
        setHits(d.results || []);
        setTotal(d.total || 0);
        setBrowsing(!!d.browsing);
        setCursor(-1);
      } catch { setHits([]); }
    }, q.trim() ? 160 : 0);
    return () => clearTimeout(timer.current);
  }, [q]);

  function pick(ticker) {
    setOpen(false);
    setQ("");
    onPick(ticker);
  }

  function onKeyDown(e) {
    if (!open || !hits.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => (c + 1) % hits.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => (c - 1 + hits.length) % hits.length); }
    else if (e.key === "Enter" && cursor >= 0) { e.preventDefault(); pick(hits[cursor].ticker); }
    else if (e.key === "Escape") setOpen(false);
  }

  return (
    <div style={{ position: "relative", flex: 1 }}>
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) pick(q.trim().toUpperCase()); }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={busy ? "Yükleniyor…" : "Şirket ara veya listeye göz at"}
          aria-label="Şirket ara"
          disabled={busy}
        />
      </form>

      {open && hits.length > 0 && (
        <ul className="combo">
          <li className="micro" style={{ padding: "4px 11px 8px", listStyle: "none" }}>
            {browsing
              ? `${total.toLocaleString("tr-TR")} şirket sorgulanabilir — en büyükleri`
              : `${total.toLocaleString("tr-TR")} sonuç`}
          </li>
          {hits.map((h, i) => (
            <li key={`${h.cik}-${h.ticker}-${i}`}>
              <button
                onMouseDown={() => pick(h.ticker)}
                onMouseEnter={() => setCursor(i)}
                style={i === cursor ? { background: "var(--page)" } : undefined}>
                <span className="tk">{h.ticker}</span>
                <span className="nm">{h.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
