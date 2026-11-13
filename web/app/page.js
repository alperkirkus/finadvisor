"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Search from "../components/Search";
import Verdict, { Fold } from "../components/Verdict";
import Interpretation from "../components/Interpretation";
import Scores from "../components/Scores";
import Trends from "../components/Trends";
import MetricTable from "../components/MetricTable";
import TopPicks from "../components/TopPicks";
import MarketRegime from "../components/MarketRegime";
import Signals from "../components/Signals";

function ThemeToggle() {
  const [theme, setTheme] = useState(null);
  useEffect(() => {
    const saved = localStorage.getItem("theme");
    if (saved) { document.documentElement.dataset.theme = saved; setTheme(saved); }
  }, []);
  function flip() {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    setTheme(next);
  }
  return (
    <button onClick={flip} aria-label="Tema değiştir" style={{ fontSize: 17, lineHeight: 1 }}>
      {theme === "dark" ? "☀" : "☾"}
    </button>
  );
}

export default function Page() {
  const [pkg, setPkg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [ticker, setTicker] = useState(null);
  const [view, setView] = useState({ tab: "companies", market: "sp500", instrument: null });
  const homeScroll = useRef(0);
  const shown = useRef(null);

  const fetchCompany = useCallback(async (t) => {
    if (shown.current == null) homeScroll.current = window.scrollY;
    shown.current = t;
    window.scrollTo(0, 0);
    setBusy(true); setError(null); setPkg(null); setTicker(t);
    try {
      const r = await fetch(`/api/company/${t}`);
      const d = await r.json();
      if (!r.ok) setError(d.detail || "yüklenemedi");
      else setPkg(d);
    } catch (e) {
      setError(String(e));
    } finally { setBusy(false); }
  }, []);

  const goHome = useCallback(() => {
    shown.current = null;
    setPkg(null); setError(null); setBusy(false); setTicker(null);
  }, []);

  // The open company lives in the URL (?t=MCD), so the browser's own back and
  // forward buttons work and a company page can be bookmarked or shared.
  useEffect(() => {
    // The home list stays mounted behind a company page and is put back
    // where it was left; the browser's own restoration would run against a
    // page whose height has not settled yet.
    history.scrollRestoration = "manual";
    function read() {
      const q = new URLSearchParams(location.search);
      if (q.get("v") === "signals") {
        setView({ tab: "signals", market: q.get("m") || "sp500", instrument: q.get("i") });
      } else if (!q.get("t")) {
        setView((cur) => ({ ...cur, tab: "companies" }));
      }
      return q.get("t");
    }
    const t = read();
    if (t) fetchCompany(t);
    function onPop() {
      const p = read();
      if (p) fetchCompany(p); else goHome();
    }
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [fetchCompany, goHome]);

  function open(t) {
    history.pushState({ t }, "", `?t=${encodeURIComponent(t)}`);
    fetchCompany(t);
  }

  // The signals view lives in the URL too (?v=signals&m=etf&i=SPY).
  function show(next) {
    const q = new URLSearchParams();
    if (next.tab === "signals") {
      q.set("v", "signals");
      q.set("m", next.market);
      if (next.instrument) q.set("i", next.instrument);
    }
    const query = q.toString();
    history.pushState({}, "", query ? `?${query}` : location.pathname);
    window.scrollTo(0, 0);
    setView(next);
  }

  function back() {
    if (history.state?.t) history.back();
    else { history.pushState({}, "", location.pathname); goHome(); }
  }

  const onCompany = ticker != null;

  useEffect(() => {
    if (!onCompany) window.scrollTo(0, homeScroll.current);
  }, [onCompany]);

  return (
    <>
      <div className="navbar">
        <div className="bar">
          {onCompany ? (
            <button className="back" onClick={back} aria-label="Geri">
              <span className="chev" aria-hidden="true">‹</span>Geri
            </button>
          ) : (
            <div className="brand">FinAdvisor</div>
          )}
          <Search onPick={open} busy={busy} />
          <ThemeToggle />
        </div>
      </div>

      <main className="sheet">
        <div hidden={onCompany}>
          <div className="tabs" role="tablist" style={{ marginTop: 12 }}>
            {[["companies", "Şirketler"], ["signals", "Sinyaller"]].map(([key, label]) => (
              <button key={key} role="tab" aria-selected={view.tab === key}
                      className={`seg ${view.tab === key ? "on" : ""}`}
                      onClick={() => show({ ...view, tab: key, instrument: null })}>
                {label}
              </button>
            ))}
          </div>
          <div hidden={view.tab !== "companies"}>
            <div style={{ margin: "0 0 32px" }}>
              <div className="display" style={{ marginBottom: 10 }}>Bilançodan karara.</div>
              <div className="lead" style={{ maxWidth: "46ch" }}>
                Şirketin SEC'e verdiği raporlardan hesaplanan sağlık, değer ve
                risk okuması. Her sayı şirketin kendi beyanından gelir.
              </div>
            </div>
            <MarketRegime />
            <TopPicks onPick={open} active={!onCompany && view.tab === "companies"} />
          </div>
          {view.tab === "signals" && (
            <Signals market={view.market} instrument={view.instrument}
                     onMarket={(m) => show({ tab: "signals", market: m, instrument: null })}
                     onInstrument={(i) => show({ ...view, instrument: i })}
                     onCompany={open} />
          )}
        </div>

        {busy && <div className="small dim" style={{ marginTop: 40 }}>Yükleniyor…</div>}

        {error && (
          <div className="group group-pad" style={{ marginTop: 24 }}>
            <div className="chip s-critical" style={{ marginBottom: 8 }}>Bulunamadı</div>
            <div className="small">{error}</div>
          </div>
        )}

        {pkg && (
          <div className="block">
            <Verdict ticker={pkg.company.ticker} company={pkg.company}>
              <Fold title="Kural tabanlı değerlendirme">
                <Interpretation ticker={pkg.company.ticker} />
              </Fold>

              <Fold title="Finansal skorlar">
                <Scores scores={pkg.scores} notApplicable={pkg.not_applicable_for_sector} />
              </Fold>

              <Fold title="Trendler"
                    count={`son ${Object.values(pkg.trends)[0]?.series.length || 0} çeyrek`}>
                <Trends trends={pkg.trends} />
              </Fold>

              <Fold title="Tüm metrikler" count="son 12 ay">
                <MetricTable
                  metrics={pkg.latest_metrics}
                  gaps={pkg.data_gaps}
                  notApplicable={pkg.not_applicable_for_sector} />
              </Fold>

              <Fold title="Veri kalitesi"
                    count={`%${Math.round(pkg.data_coverage * 100)}`}>
                <div className="small">
                  {pkg.periods_available} dönem geçmiş, {pkg.as_of} itibarıyla.
                  Kapsam %{Math.round(pkg.data_coverage * 100)}.
                  {pkg.data_gaps.length > 0 && (
                    <> Şirketin raporlamadığı kalemler: {pkg.data_gaps.join(", ")} —
                    bunlara dayanan çıkarımlar zayıftır.</>
                  )}
                </div>
                <div className="micro" style={{ marginTop: 12 }}>{pkg.source}</div>
              </Fold>
            </Verdict>
          </div>
        )}
      </main>
    </>
  );
}
