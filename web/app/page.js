"use client";
import { useCallback, useEffect, useState } from "react";
import Search from "../components/Search";
import Verdict, { Fold } from "../components/Verdict";
import Interpretation from "../components/Interpretation";
import Scores from "../components/Scores";
import Trends from "../components/Trends";
import MetricTable from "../components/MetricTable";
import TopPicks from "../components/TopPicks";

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

  const fetchCompany = useCallback(async (t) => {
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
    setPkg(null); setError(null); setBusy(false); setTicker(null);
  }, []);

  // The open company lives in the URL (?t=MCD), so the browser's own back and
  // forward buttons work and a company page can be bookmarked or shared.
  useEffect(() => {
    const t = new URLSearchParams(location.search).get("t");
    if (t) fetchCompany(t);
    function onPop() {
      const p = new URLSearchParams(location.search).get("t");
      if (p) fetchCompany(p); else goHome();
    }
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [fetchCompany, goHome]);

  function open(t) {
    history.pushState({ t }, "", `?t=${encodeURIComponent(t)}`);
    window.scrollTo(0, 0);
    fetchCompany(t);
  }

  function back() {
    if (history.state?.t) history.back();
    else { history.pushState({}, "", location.pathname); goHome(); }
    window.scrollTo(0, 0);
  }

  const onCompany = ticker != null;

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
        {!onCompany && (
          <>
            <div style={{ margin: "28px 0 32px" }}>
              <div className="display" style={{ marginBottom: 10 }}>Bilançodan karara.</div>
              <div className="lead" style={{ maxWidth: "46ch" }}>
                Şirketin SEC'e verdiği raporlardan hesaplanan sağlık, değer ve
                risk okuması. Her sayı şirketin kendi beyanından gelir.
              </div>
            </div>
            <TopPicks onPick={open} />
          </>
        )}

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
