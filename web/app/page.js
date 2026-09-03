"use client";
import { useEffect, useState } from "react";
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
    <button onClick={flip} aria-label="Tema değiştir" style={{ fontSize: 15, lineHeight: 1 }}>
      {theme === "dark" ? "☀" : "☾"}
    </button>
  );
}

export default function Page() {
  const [pkg, setPkg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function load(ticker) {
    setBusy(true); setError(null); setPkg(null);
    try {
      const r = await fetch(`/api/company/${ticker}`);
      const d = await r.json();
      if (!r.ok) setError(d.detail || "yüklenemedi");
      else setPkg(d);
    } catch (e) {
      setError(String(e));
    } finally { setBusy(false); }
  }

  return (
    <>
      <div className="bar">
        <div className="brand">FinAdvisor</div>
        <Search onPick={load} busy={busy} />
        <ThemeToggle />
      </div>

      <main className="sheet">
        {!pkg && !error && !busy && (
          <div style={{ marginTop: 70, maxWidth: "44ch" }}>
            <div className="display" style={{ marginBottom: 18 }}>
              Bilançodan karara.
            </div>
            <div className="lead">
              SEC'e verilen 10-K ve 10-Q raporlarından deterministik finansal
              analiz. Her sayı şirketin kendi beyanından hesaplanır — hiçbiri
              tahmin edilmez.
            </div>
            <div className="micro" style={{ marginTop: 34 }}>
              Arama alanına dokunun, 10.412 şirket listelenir.
            </div>
          </div>
        )}

        {!pkg && !error && !busy && <TopPicks onPick={load} />}

        {busy && <div className="small dim" style={{ marginTop: 60 }}>Yükleniyor…</div>}

        {error && (
          <div className="note s-critical" style={{ marginTop: 60 }}>
            <div className="chip s-critical" style={{ marginBottom: 4 }}>
              <span className="g" aria-hidden="true">▼</span>
              <span style={{ color: "var(--ink)" }}>Bulunamadı</span>
            </div>
            <div className="small">{error}</div>
          </div>
        )}

        {pkg && (
          <div className="block">
            <Verdict ticker={pkg.company.ticker} company={pkg.company}>
              <Fold title="Değerlendirme">
                <Interpretation ticker={pkg.company.ticker} />
              </Fold>

              <Fold title="Skorlar">
                <Scores scores={pkg.scores} notApplicable={pkg.not_applicable_for_sector} />
              </Fold>

              <Fold title="Trendler"
                    count={`son ${Object.values(pkg.trends)[0]?.series.length || 0} çeyrek`}>
                <Trends trends={pkg.trends} />
              </Fold>

              <Fold title="Tüm metrikler" count="TTM">
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
