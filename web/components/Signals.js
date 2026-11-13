"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

function pct(v, d = 1) {
  if (v == null) return "–";
  const text = (v * 100).toFixed(d).replace(".", ",");
  const zero = Number((v * 100).toFixed(d)) === 0;
  return `${v > 0 && !zero ? "+" : ""}${zero ? text.replace("-", "") : text}%`;
}
const share = (v) => (v == null ? "–" : `%${Math.round(v * 100)}`);
const price = (v) =>
  v == null ? "–" : v.toLocaleString("tr-TR", {
    minimumFractionDigits: 2, maximumFractionDigits: v < 10 ? 3 : 2 });
const count = (v) => (v == null ? "–" : Math.round(v).toLocaleString("tr-TR"));
const day = (iso) =>
  iso ? new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short", year: "numeric" }) : "–";
const shortDay = (iso) =>
  iso ? new Date(iso).toLocaleDateString("tr-TR", { day: "numeric", month: "short" }) : "–";
const tone = (v) => (v == null ? "neutral" : v > 0 ? "good" : "critical");
function inR(v, d = 2) {
  if (v == null) return "–";
  const text = v.toFixed(d).replace(".", ",");
  const zero = Number(v.toFixed(d)) === 0;
  return `${v > 0 && !zero ? "+" : ""}${zero ? text.replace("-", "") : text}R`;
}
// The share of the account a position takes when the trade risks `budget`
// of it and no position may exceed `cap`.
const sizeOf = (risk, budget, cap) => (risk ? Math.min(budget / risk, cap) : null);
const riskOf = (v) => (v == null ? "–" : `%${(v * 100).toFixed(1).replace(".", ",")}`);

const PERIODS = [
  ["discover", "2006–2016"],
  ["validate", "2017–2021"],
  ["sealed", "2022–2025"],
];
const REASON = { exit: "Çıkış kuralı", stop: "Stop", target: "Hedef", stall: "İlerlemedi",
                 time: "Süre doldu", end: "İşlem durdu", open: "Açık", pending: "Giriş bekliyor" };
// A stop the price opened under is filled at the open, further than 1R.
const reasonOf = (t) => (t.reason === "stop" && t.gapped ? "Stop (açılış boşluğu)" : REASON[t.reason]);
const VERDICT = {
  "yatirim yapilabilir": ["good", "Yatırım yapılabilir"], "ucuz ama sorunlu": ["warning", "Ucuz ama sorunlu"],
  "kosullu": ["warning", "Koşullu"], "iyi sirket, pahali fiyat": ["warning", "İyi şirket, pahalı fiyat"],
  "fiyatlanamaz": ["neutral", "Fiyatlanamaz"], "fiyat verisi yok": ["neutral", "Fiyat verisi yok"],
  "degerlendirilemez": ["neutral", "Değerlendirilemez"], "yatirim yapilamaz": ["critical", "Yatırım yapılamaz"],
};
const REGIME = {
  up: ["Yükseliş piyasası", "enstrümanların %60'ından fazlası 200 günlük ortalamasının üstünde"],
  mixed: ["Kararsız piyasa", "%40 ile %60 arası"],
  down: ["Düşüş piyasası", "%40'ından azı 200 günlük ortalamasının üstünde"],
};

function Segments({ options, value, onChange, label, className = "filters" }) {
  return (
    <div className={className} role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.key} className={`seg ${value === o.key ? "on" : ""}`}
                aria-pressed={value === o.key} onClick={() => onChange(o.key)}>
          {o.label}{o.count != null && <> <span className="num dim">{o.count}</span></>}
        </button>
      ))}
    </div>
  );
}

// Every position here is a purchase; the badge says so, so that buying a
// dip is never read as a bet on a fall.
const Side = () => (
  <span className="chip side" title="Alış yönlü işlem: önce alınır, sonra satılır">▲ Alış</span>
);

function Status({ state, closing, days }) {
  if (state === "pending") return <span className="chip s-good">Yeni sinyal · yarın açılışta alınır</span>;
  if (closing) return <span className="chip s-warning">Yarın açılışta satılır · {days}. gün</span>;
  return <span className="chip s-accent">Pozisyonda · {days}. gün</span>;
}

function Field({ label, children }) {
  return (
    <div className="field">
      <div className="micro">{label}</div>
      <div className="num">{children}</div>
    </div>
  );
}

/* One position or one fresh signal, as labelled figures rather than a
   sentence: what was paid, where it stands, where it is cut. */
function SignalCard({ s, d, index, onOpen }) {
  const pending = s.state === "pending";
  const size = sizeOf(s.risk, d.risk_per_trade, d.position_cap);
  return (
    <button className="sigcard rise" style={{ "--i": index }} onClick={() => onOpen(s.instrument)}>
      <div className="sigcard-top">
        <span className="title">{s.instrument}</span>
        {s.name !== s.instrument && <span className="dim small">{s.name}</span>}
        <Side />
        <span style={{ marginLeft: "auto" }}>
          <Status state={s.state} closing={s.closing} days={s.days} />
        </span>
      </div>
      <div className="fields">
        <Field label={pending ? "Alış" : `Alış · ${shortDay(s.entry)}`}>
          {pending ? "yarın açılışta" : price(s.entry_price)}
        </Field>
        <Field label="Son fiyat">{price(s.exit_price)}</Field>
        <Field label="Kâr / zarar">
          {pending ? "–" : (
            <span className={`s-${tone(s.net)}`}>
              {pct(s.net)} <span className="dim">({inR(s.r, 1)})</span>
            </span>
          )}
        </Field>
        <Field label="Zarar kes (stop)">{price(s.stop_now ?? s.stop)}</Field>
        <Field label="Risk (1R)">fiyatın {riskOf(s.risk)}'i</Field>
        <Field label="Pozisyon payı">hesabın {share(size)}'i</Field>
      </div>
      <div className="micro sigcard-foot">
        {s.agree?.length > 0 && <>Sinyali veren {s.agree.length} kural: {s.agree.join(", ")}. </>}
        Bu enstrümanda geçmişte {s.own.trades} işlem, {s.own.wins} kazanç
        {s.own.net != null && <>, işlem başı {pct(s.own.net)}</>}.
        <span className="dim"> · {s.title}</span>
      </div>
    </button>
  );
}

/* What a system did, period by period. Profit per trade is the number the
   list is chosen by; beside it the same result in R (the trade's initial
   risk as the unit), and the edge: the part a random purchase of the same
   length would not have made. */
function Record({ system, cost = 0 }) {
  const later = [["2026", system.after], ["Kural sonrası", system.forward]];
  const base = system.baseline;
  // What is left of the edge over a random purchase once a round trip is paid.
  const left = (edge) => (edge == null ? null : edge - 2 * cost);
  return (
    <div className="sigrecord">
      <div className="sighead micro">
        <span>Dönem</span><span>İşlem</span><span>Kazanan</span>
        <span>Ort. kazanç / kayıp</span><span>İşlem başı net</span>
        <span>R: ort. (kazanç / kayıp)</span><span>Rastgele alışa göre, komisyon sonrası</span>
      </div>
      {PERIODS.map(([key, label]) => {
        const p = system.periods[key];
        return (
          <div className="sigrow small" key={key}>
            <span>{label}</span>
            <span className="num">{p.trades?.toLocaleString("tr-TR") ?? "–"}</span>
            <span className="num">{share(p.win_rate)}</span>
            <span className="num">{pct(p.avg_win)} / {pct(p.avg_loss)}</span>
            <span className={`num s-${tone(p.expectancy)}`}>{pct(p.expectancy, 2)}</span>
            <span className="num">
              <span className={`s-${tone(p.avg_r)}`}>{inR(p.avg_r)}</span>
              {p.avg_r != null && (
                <span className="dim"> ({inR(p.avg_win_r, 1)} / {inR(p.avg_loss_r, 1)})</span>
              )}
            </span>
            <span className={`num s-${tone(left(p.edge))}`}>{pct(left(p.edge), 2)}</span>
            {base && (
              <>
                <span className="dim micro">seçim yapmadan, her sinyal</span>
                <span className="num dim">{base[key].trades?.toLocaleString("tr-TR") ?? "–"}</span>
                <span className="num dim">{share(base[key].win_rate)}</span>
                <span className="num dim">{pct(base[key].avg_win)} / {pct(base[key].avg_loss)}</span>
                <span className="num dim">{pct(base[key].expectancy, 2)}</span>
                <span className="num dim">{inR(base[key].avg_r)}</span>
                <span className="num dim">{pct(left(base[key].edge), 2)}</span>
              </>
            )}
          </div>
        );
      })}
      {later.map(([label, p]) => (
        <div className="sigrow small" key={label}>
          <span>{label}</span>
          <span className="num">{p.trades}</span>
          <span className="num">{p.trades ? share(p.wins / p.trades) : "–"}</span>
          <span className="num dim">–</span>
          <span className={`num s-${tone(p.net)}`}>{pct(p.net, 2)}</span>
          <span className={`num s-${tone(p.r)}`}>{inR(p.r)}</span>
          <span className="num dim">–</span>
        </div>
      ))}
    </div>
  );
}

function SystemCard({ system, startOpen = false, cost = 0 }) {
  const [open, setOpen] = useState(startOpen);
  const sealed = system.periods.sealed;
  return (
    <div className="cell" style={{ display: "block" }}>
      <button className="sigtitle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>
          <span className="title">{system.title}</span>
          {system.combined && (
            <span className="dim small"> · {system.members} kuralın ortak kararı</span>
          )}
          {system.status === "marked" && (
            <span className="chip s-warning" style={{ marginLeft: 8 }}>2022–25'te tutmadı</span>
          )}
        </span>
        <span className="small" style={{ whiteSpace: "nowrap" }}>
          <span className={`num s-${tone(sealed.expectancy)}`}>{pct(sealed.expectancy, 2)}</span>
          <span className="dim"> işlem başı · {share(sealed.win_rate)} kazanan {open ? "⌃" : "⌄"}</span>
        </span>
      </button>
      {open && (
        <div className="fade" style={{ marginTop: 10 }}>
          <div className="small">{system.rule}</div>
          <div className="micro" style={{ margin: "6px 0 12px" }}>
            Alış, sinyalden sonraki açılışta yapılır. {system.stop_text}
            {` En çok ${system.max_days} işlem günü tutulur.`}
            {sealed.risk != null &&
              ` Stop mesafesi (1R) 2022–25'te ortalama fiyatın ${riskOf(sealed.risk)}'i; işlemlerin ${share(sealed.stopped)}'i stopla kapandı.`}
          </div>
          <Record system={system} cost={cost} />
        </div>
      )}
    </div>
  );
}

/* The independent judge's finding, stated before anything that could be
   read as a suggestion to trade: what an account that follows the
   algorithm made, against what holding the market made. */
function Verdict({ systems, currency }) {
  const rows = systems.filter((s) => s.performance);
  if (!rows.length) return null;
  const worth = rows.some((s) => s.performance.account.yearly > s.performance.holding.yearly);
  return (
    <div className={`group group-pad verdict ${worth ? "" : "no"}`}>
      <div className="small">
        <b>{worth ? "Dikkatle okunmalı." : "Bu liste işlem önerisi değildir: algoritma işlem yapmaya değmiyor."}</b>
      </div>
      {rows.map((s) => {
        const p = s.performance;
        return (
          <div className="small" key={s.id} style={{ marginTop: 6 }}>
            {s.title}: {p.since}'den beri {p.slots} pozisyonluk bir hesap yılda{" "}
            <span className={`num s-${tone(p.account.yearly)}`}>{pct(p.account.yearly, 1)}</span> getirdi;
            aynı dönemde piyasayı olduğu gibi tutmak yılda{" "}
            <span className="num">{pct(p.holding.yearly, 1)}</span>. İşlem başı {inR(p.avg_r)}, kazanan{" "}
            {share(p.win_rate)}.
          </div>
        );
      })}
      <div className="micro" style={{ marginTop: 8 }}>
        Bağımsız değerlendirme, 13 Kas 2026: bu kuralların kazancı piyasada bulunmanın getirisidir;
        hiçbiri endeksi tutmaktan fazla para kazandırmadı ve bir hesap sinyallerin çoğunu alamıyor.
        {currency === "TRY" && " BIST rakamları nominal liradır."} Ayrıntı "Performans" sekmesinde.
      </div>
    </div>
  );
}

function useCountUp(target, ms = 700) {
  const [v, setV] = useState(target);
  useEffect(() => {
    if (target == null || typeof window === "undefined"
        || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setV(target);
      return undefined;
    }
    let frame;
    const start = performance.now();
    const step = (now) => {
      const k = Math.min((now - start) / ms, 1);
      setV(target * (1 - (1 - k) ** 3));
      if (k < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, ms]);
  return v;
}

function Tile({ label, value, format, toneOf, hint }) {
  const shown = useCountUp(value);
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`num ${toneOf ? `s-${tone(value)}` : ""}`} style={{ fontSize: 24, fontWeight: 600 }}>
        {format(shown)}
      </div>
      {hint && <div className="micro" style={{ marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

const BW = 720, BH = 190;

/* Average result of a trade in each year, in R. One measure, so one colour
   per sign; the years the algorithm was fitted on are drawn fainter and
   said to be so in words under the chart. */
function YearBars({ rows }) {
  const [hover, setHover] = useState(null);
  const top = Math.max(...rows.map((r) => Math.abs(r.avg_r)), 0.05) * 1.15;
  const left = 38, bottom = 20, plot = BH - bottom - 8;
  const zero = 8 + plot / 2;
  const step = (BW - left) / rows.length;
  const h = (v) => (Math.abs(v) / top) * (plot / 2);
  const at = hover != null ? rows[hover] : null;
  return (
    <div style={{ position: "relative" }} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${BW} ${BH}`} width="100%" role="img"
           aria-label="Yıllara göre işlem başı ortalama sonuç, R olarak">
        {[top / 1.15, 0, -top / 1.15].map((g) => (
          <g key={g}>
            <line x1={left} x2={BW} y1={zero - (g / top) * (plot / 2)} y2={zero - (g / top) * (plot / 2)}
                  stroke="var(--hair)" strokeWidth="1" />
            <text x={left - 6} y={zero - (g / top) * (plot / 2) + 4} textAnchor="end"
                  fontSize="10" fill="var(--ink-3)">{inR(g, 1)}</text>
          </g>
        ))}
        {rows.map((r, i) => (
          <g key={r.year} onMouseEnter={() => setHover(i)}>
            <rect x={left + i * step} y={8} width={step} height={plot} fill="transparent" />
            <rect className="bar" style={{ "--i": i }}
                  x={left + i * step + 2} width={Math.max(step - 4, 2)} rx="3"
                  y={r.avg_r >= 0 ? zero - h(r.avg_r) : zero} height={Math.max(h(r.avg_r), 1)}
                  fill={`var(--${r.avg_r >= 0 ? "good" : "critical"})`}
                  opacity={r.fitted ? 0.35 : hover === i ? 1 : 0.9} />
            <text x={left + i * step + step / 2} y={BH - 6} textAnchor="middle" fontSize="10"
                  fill="var(--ink-3)">{`'${r.year.slice(2)}`}</text>
          </g>
        ))}
      </svg>
      {at && (
        <div className="tip" style={{
          left: `${Math.min(Math.max(((left + (hover + 0.5) * step) / BW) * 100, 18), 82)}%`,
          top: 0, transform: "translate(-50%, -100%)" }}>
          {at.year}{at.fitted ? " (öğrenme dönemi)" : ""} · {count(at.trades)} işlem · {share(at.win_rate)} kazanan
          · işlem başı {inR(at.avg_r)} ({pct(at.net, 2)})
        </div>
      )}
    </div>
  );
}

/* The questions an owner asks of an algorithm, answered from the years it
   was not fitted on. */
function Performance({ system, d }) {
  const p = system.performance;
  const [more, setMore] = useState(false);
  if (!p) {
    return <div className="group group-pad small dim">Bu algoritmanın 2017'den beri yeterli işlemi yok.</div>;
  }
  const wins = Math.round(p.win_rate * 100);
  const cost = d.cost_per_side;
  const good = p.by_instrument.filter((x) => x.avg_r > 0).length;
  const rows = more || p.by_instrument.length <= 12
    ? p.by_instrument : [...p.by_instrument.slice(0, 6), ...p.by_instrument.slice(-6)];
  const a = p.account;
  return (
    <div className="fade">
      <div className="group">
        <div className="tiles four">
          <Tile label={`İşlem (${p.since}'den beri)`} value={p.trades} format={count}
                hint={`yılda yaklaşık ${count(p.per_year)} sinyal`} />
          <Tile label="Kazanan işlem" value={p.win_rate} format={share}
                hint={`başabaş için gereken ${share(p.breakeven_win_rate)}`} />
          <Tile label="İşlem başı net kâr" value={p.net} format={(v) => pct(v, 2)} toneOf
                hint={`komisyon öncesi ${pct(p.gross, 2)}`} />
          <Tile label="İşlem başı R" value={p.avg_r} format={(v) => inR(v)} toneOf
                hint={`1R = fiyatın ${riskOf(p.risk)}'i · her sinyal alınsa toplam ${inR(p.sum_r, 0)}`} />
        </div>
      </div>

      <div className="group group-pad" style={{ marginTop: 14 }}>
        <div className="small">
          <b>100 işlemde:</b> {wins} tanesi kazanır, ortalama{" "}
          <span className="s-good num">{pct(p.avg_win)}</span> ({inR(p.avg_win_r, 1)}); {100 - wins} tanesi
          kaybeder, ortalama <span className="s-critical num">{pct(p.avg_loss)}</span> ({inR(p.avg_loss_r, 1)}).
          {p.avg_win < -p.avg_loss
            ? " Kazançlar kayıplardan küçük; sistem kazanan oranıyla ayakta duruyor."
            : " Kazançlar kayıplardan büyük; sistem az sayıda büyük kazançla ayakta duruyor."}
        </div>
        <div className="micro" style={{ marginTop: 8 }}>
          Ortalama işlem {p.avg_days.toFixed(1).replace(".", ",")} gün sürer. İşlemlerin {share(p.stopped)}'i
          stopla kapandı; {share(p.gapped)}'inde fiyat stopun altında açıldı (kayıp 1R'den büyük). En kötü
          işlem {pct(p.worst)}, en iyi {pct(p.best)}.
        </div>
      </div>

      <div className="section-title" style={{ marginTop: 26 }}>Her sinyali alamayan bir hesap</div>
      <div className="group">
        <div className="tiles four">
          <Tile label="Yıllık getiri" value={a.yearly} format={(v) => pct(v, 1)} toneOf />
          <Tile label="En derin düşüş" value={a.drawdown} format={(v) => pct(v, 0)} />
          <Tile label="Yılda alınan işlem" value={a.trades_per_year} format={count}
                hint={`${count(a.offered_per_year)} sinyalden`} />
          <Tile label="Üst üste en çok kayıp" value={a.longest_losing_run} format={count} hint="işlem" />
        </div>
      </div>
      <div className="group group-pad" style={{ marginTop: 14 }}>
        <div className="small">
          <b>Aynı dönemde piyasayı olduğu gibi tutmak:</b> yılda{" "}
          <span className="num">{pct(p.holding.yearly, 1)}</span>, en derin düşüş{" "}
          <span className="num">{pct(p.holding.drawdown, 0)}</span>.{" "}
          {a.yearly > p.holding.yearly
            ? "Algoritma bunu geçti."
            : "Algoritma bunun gerisinde kaldı; bu hâliyle işlem yapmaya değmez."}
        </div>
      </div>
      <div className="section-foot">
        Hesap: aynı anda en çok {p.slots} pozisyon, her biri hesabın en çok %{d.position_cap * 100}'si, her
        işlemde hesabın %{d.risk_per_trade * 100}'i riskte; yer yokken gelen sinyal alınmaz. {p.since}'den{" "}
        {day(p.through)} tarihine, komisyon dahil. Sermayenin ortalama {share(a.invested)}'i yatırımdaydı.
        Düşüş kapanan işlemlerden hesaplanır; gün içindeki en kötü an daha derindir. "Piyasayı tutmak":
        her gün listedeki bütün enstrümanlar eşit ağırlıkla, komisyonsuz.
        {d.currency === "TRY" && " Getiri nominal liradır; enflasyon düşülmemiştir."}
      </div>

      <div className="section-title" style={{ marginTop: 26 }}>Yıllara göre</div>
      <div className="group group-pad">
        <YearBars rows={p.by_year} />
        <div className="micro" style={{ marginTop: 6 }}>
          Çubuk, o yıl açılan işlemlerin ortalama sonucudur (R). Soluk yıllar algoritmanın öğrenildiği
          dönemdir ve yukarıdaki özetlerin hiçbirinde sayılmaz.
        </div>
      </div>

      <div className="section-title" style={{ marginTop: 26 }}>Piyasanın durumuna göre</div>
      <div className="group">
        <div className="perfrow sighead micro">
          <span>Sinyal günü</span><span>İşlem</span><span>Kazanan</span><span>İşlem başı net</span><span>R</span>
        </div>
        {p.by_regime.map((r) => (
          <div className="perfrow small" key={r.regime}>
            <span>{REGIME[r.regime][0]} <span className="dim micro">· {REGIME[r.regime][1]}</span></span>
            <span className="num">{count(r.trades)}</span>
            <span className="num">{share(r.win_rate)}</span>
            <span className={`num s-${tone(r.net)}`}>{pct(r.net, 2)}</span>
            <span className={`num s-${tone(r.avg_r)}`}>{inR(r.avg_r)}</span>
          </div>
        ))}
      </div>

      <div className="section-title" style={{ marginTop: 26 }}>Komisyon değişirse</div>
      <div className="group">
        <div className="perfrow sighead micro">
          <span>Tek yön maliyet (komisyon + alış-satış farkı)</span><span /><span>Kazanan</span>
          <span>İşlem başı net</span><span />
        </div>
        {p.costs.map((c) => (
          <div className="perfrow small" key={c.per_side}>
            <span>
              %{(c.per_side * 100).toFixed(2).replace(".", ",")}
              {Math.abs(c.per_side - cost) < 1e-9 && (
                <span className="chip s-accent" style={{ marginLeft: 8 }}>hesaplarda kullanılan</span>
              )}
            </span>
            <span />
            <span className="num">{share(c.win_rate)}</span>
            <span className={`num s-${tone(c.net)}`}>{pct(c.net, 2)}</span>
            <span />
          </div>
        ))}
      </div>

      <div className="section-title" style={{ marginTop: 26 }}>
        Enstrümandan enstrümana{" "}
        <span className="dim">· {p.by_instrument.length} enstrümanın {good} tanesi artıda</span>
      </div>
      <div className="group">
        <div className="perfrow sighead micro">
          <span>Enstrüman (en az 10 işlem)</span><span>İşlem</span><span>Kazanan</span>
          <span>İşlem başı net</span><span>R</span>
        </div>
        {rows.map((r, i) => (
          <div className="perfrow small" key={r.instrument}
               style={!more && p.by_instrument.length > 12 && i === 6
                 ? { borderTop: "2px solid var(--hair)" } : undefined}>
            <span>
              {r.instrument}
              {r.name !== r.instrument && <span className="dim micro"> · {r.name}</span>}
            </span>
            <span className="num">{count(r.trades)}</span>
            <span className="num">{share(r.win_rate)}</span>
            <span className={`num s-${tone(r.net)}`}>{pct(r.net, 2)}</span>
            <span className={`num s-${tone(r.avg_r)}`}>{inR(r.avg_r)}</span>
          </div>
        ))}
        {p.by_instrument.length > 12 && (
          <button className="listbtn more" onClick={() => setMore(!more)}>
            {more ? "Yalnızca en iyi ve en kötü 6'yı göster" : `Tümünü göster (${p.by_instrument.length})`}
          </button>
        )}
      </div>
      <div className="section-foot">
        {d.market === "sp500"
          ? "Bu sayfa, 2017'den beri endekste bulunmuş bütün şirketler üzerindedir; endeksten çıkanlar dahildir."
          : "Bu sayfa bugün işlem gören enstrümanlar üzerindedir; listeden çıkmış olanlar yoktur, bu yüzden sonuçlar gerçekte olacağından iyi görünür."}
        {" "}"Her sinyal alınsa" toplamı hiçbir hesabın ulaşamayacağı bir üst sınırdır.
      </div>
    </div>
  );
}

const W = 720, H = 300, PL = 6, PR = 52, PT = 12, PB = 22;
const RANGES = [{ key: 60, label: "3 ay" }, { key: 125, label: "6 ay" }, { key: 250, label: "1 yıl" },
                { key: 750, label: "3 yıl" }];

/* Daily candles: body from open to close, wick from low to high, green
   when the day closed up. A trade is the band from its purchase to its
   sale, with its stop as a dashed line while it is open. */
function CandleChart({ prices, trades, through }) {
  const [hover, setHover] = useState(null);
  const [range, setRange] = useState(125);
  const box = useRef(null);
  const view = useMemo(() => prices.slice(-range), [prices, range]);
  const index = useMemo(() => new Map(view.map((p, i) => [p[0], i])), [view]);
  if (view.length < 2) return null;
  const held = trades.find((t) => t.entry && !t.exit);
  const stop = held ? held.stop_now ?? held.stop : null;
  let lo = Math.min(...view.map((p) => p[3])), hi = Math.max(...view.map((p) => p[2]));
  if (stop != null && stop > lo * 0.7) lo = Math.min(lo, stop);
  const pad = (hi - lo) * 0.06 || 1;
  lo -= pad; hi += pad;
  const step = (W - PL - PR) / view.length;
  const x = (i) => PL + (i + 0.5) * step;
  const y = (v) => PT + (1 - (v - lo) / (hi - lo)) * (H - PT - PB);
  const body = Math.max(Math.min(step * 0.7, 9), 1);
  const first = view[0][0];
  const bands = trades
    .filter((t) => t.entry && (t.exit || through) >= first)
    .map((t) => {
      const a = index.get(t.entry) ?? 0;
      const b = t.exit ? index.get(t.exit) ?? view.length - 1 : view.length - 1;
      return { t, a, b: Math.max(b, a) };
    });
  const at = hover ?? view.length - 1;
  const inside = bands.find((b) => at >= b.a && at <= b.b);
  const grid = [0.1, 0.35, 0.6, 0.85].map((k) => lo + (hi - lo) * k);
  const open = bands.find((b) => !b.t.exit);

  function onMove(e) {
    const r = box.current.getBoundingClientRect();
    const rel = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(view.length - 1, Math.floor((rel - PL) / step))));
  }
  const bar = view[at];

  return (
    <>
      <div className="chart-head">
        <div className="micro num">
          {day(bar[0])} · Açılış {price(bar[1])} · Yüksek {price(bar[2])} · Düşük {price(bar[3])} ·{" "}
          <span className={`s-${bar[4] >= bar[1] ? "good" : "critical"}`}>Kapanış {price(bar[4])}</span>
        </div>
        <Segments label="Aralık" value={range} onChange={(k) => { setRange(k); setHover(null); }}
                  options={RANGES} className="filters tight" />
      </div>
      <div ref={box} style={{ position: "relative" }} onMouseMove={onMove}
           onMouseLeave={() => setHover(null)}>
        <svg key={range} viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
             aria-label={`Son ${view.length} işlem gününün mum grafiği ve ${bands.length} işlem`}>
          {grid.map((g) => (
            <g key={g}>
              <line x1={PL} x2={W - PR} y1={y(g)} y2={y(g)} stroke="var(--hair)" strokeWidth="1" />
              <text x={W - PR + 6} y={y(g) + 4} fontSize="10" fill="var(--ink-3)">{price(g)}</text>
            </g>
          ))}
          {bands.map(({ t, a, b }, i) => (
            <g key={i} className="fade">
              <rect x={x(a) - step / 2} width={Math.max(x(b) - x(a) + step, 2)} y={PT}
                    height={H - PT - PB} fill={`var(--${t.exit ? tone(t.net) : "accent"})`} opacity="0.1" />
              <path d={`M${x(a) - 5},${H - PB + 11} L${x(a) + 5},${H - PB + 11} L${x(a)},${H - PB + 3} Z`}
                    fill={`var(--${t.exit ? tone(t.net) : "accent"})`} />
            </g>
          ))}
          {view.map((p, i) => {
            const up = p[4] >= p[1];
            const top = y(Math.max(p[1], p[4])), bottom = y(Math.min(p[1], p[4]));
            return (
              <g key={p[0]} className="candle" style={{ "--d": `${(i / view.length) * 500}ms` }}
                 fill={`var(--${up ? "good" : "critical"})`} stroke={`var(--${up ? "good" : "critical"})`}>
                <line x1={x(i)} x2={x(i)} y1={y(p[2])} y2={y(p[3])} strokeWidth="1" />
                <rect x={x(i) - body / 2} width={body} y={top} height={Math.max(bottom - top, 1)}
                      stroke="none" rx={body > 4 ? 1 : 0} />
              </g>
            );
          })}
          {open && stop != null && stop > lo && (
            <g className="fade">
              <line x1={x(open.a)} x2={W - PR} y1={y(stop)} y2={y(stop)} stroke="var(--critical)"
                    strokeWidth="1.5" strokeDasharray="5 4" />
              <text x={W - PR + 6} y={y(stop) + 4} fontSize="10" fill="var(--ink-2)">stop</text>
            </g>
          )}
          {hover !== null && (
            <line x1={x(at)} x2={x(at)} y1={PT} y2={H - PB} stroke="var(--ink-3)" strokeWidth="1" />
          )}
        </svg>
        <div className="micro" style={{ display: "flex", justifyContent: "space-between", paddingRight: 52 }}>
          <span>{day(view[0][0])}</span><span>{day(view[view.length - 1][0])}</span>
        </div>
        {hover !== null && inside && (
          <div className="tip" style={{
            left: `${Math.min(Math.max((x(at) / W) * 100, 18), 82)}%`, top: 0,
            transform: "translate(-50%, -100%)" }}>
            {inside.t.exit
              ? `Alış ${shortDay(inside.t.entry)} · satış ${shortDay(inside.t.exit)} · ${pct(inside.t.net)} (${inR(inside.t.r, 1)})`
              : `Alış ${shortDay(inside.t.entry)} · açık · ${pct(inside.t.net)} (${inR(inside.t.r, 1)})`}
          </div>
        )}
      </div>
    </>
  );
}

function Journal({ market, instrument, onCompany }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [pick, setPick] = useState(null);
  const [all, setAll] = useState(false);
  const [single, setSingle] = useState(false);

  useEffect(() => {
    let live = true;
    setD(null); setError(null); setPick(null); setAll(false); setSingle(false);
    fetch(`/api/signals/${market}/${encodeURIComponent(instrument)}`)
      .then(async (r) => {
        const body = await r.json();
        if (!live) return;
        if (!r.ok) setError(body.detail || "yüklenemedi");
        else setD(body);
      })
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [market, instrument]);

  if (error) return <div className="group group-pad small">{error}</div>;
  if (!d) return <div className="small dim" style={{ marginTop: 24 }}>Yükleniyor…</div>;
  if (!d.systems.length) {
    return <div className="group group-pad small">Bu enstrümanda hiçbir kural işlem açmamış.</div>;
  }
  const joint = d.systems.filter((s) => s.combined);
  const singles = d.systems.filter((s) => !s.combined);
  const system = d.systems.find((s) => s.id === pick) || joint.find((s) => s.state !== "flat")
    || joint[0] || d.systems.find((s) => s.state !== "flat" && s.status === "listed") || d.systems[0];
  const rows = all ? system.trades : system.trades.slice(0, 10);
  const own = system.own;
  const chips = (list) => list.map((s) => ({
    key: s.id, count: s.own.trades, label: `${s.state === "flat" ? "" : "● "}${s.title}`,
  }));
  const now = joint.find((s) => s.state !== "flat");
  const last = now?.trades[0];
  const f = d.fundamental;

  return (
    <div className="fade">
      <div style={{ margin: "8px 0 18px" }}>
        <div className="display" style={{ fontSize: 30 }}>{d.instrument}</div>
        <div className="lead">
          {d.name !== d.instrument ? d.name : null}
          {market === "sp500" && (
            <button className="link" style={{ marginLeft: d.name !== d.instrument ? 10 : 0 }}
                    onClick={() => onCompany(d.instrument)}>
              Şirket sayfası ›
            </button>
          )}
        </div>
      </div>

      <div className="group group-pad sigsummary">
        <div>
          <div className="label micro">Kısa vade · günler, haftalar</div>
          {joint.length === 0 && <div className="small">Bu piyasada birleşik algoritma yok.</div>}
          {joint.length > 0 && !now && (
            <div className="small">
              Şu an sinyal yok.
              <div className="micro" style={{ marginTop: 4 }}>
                Geçmişte {joint.map((s) =>
                  `${s.title}: ${s.own.trades} işlem, ${s.own.wins} kazanç`).join(" · ")}.
              </div>
            </div>
          )}
          {now && (
            <div className="small">
              <Side /> <Status state={now.state} closing={last.closing} days={last.days} />
              <div className="fields two" style={{ marginTop: 10 }}>
                <Field label="Alış">{last.entry ? price(last.entry_price) : "yarın açılışta"}</Field>
                <Field label="Kâr / zarar">
                  {last.entry
                    ? <span className={`s-${tone(last.net)}`}>{pct(last.net)} ({inR(last.r, 1)})</span> : "–"}
                </Field>
                <Field label="Zarar kes (stop)">{price(last.stop_now ?? last.stop)}</Field>
                <Field label="Riske edilen (1R)">fiyatın {riskOf(last.risk)}'i</Field>
              </div>
              {last.agree?.length > 0 && (
                <div className="micro" style={{ marginTop: 8 }}>
                  Sinyali veren {last.agree.length} kural: {last.agree.join(", ")}.
                </div>
              )}
            </div>
          )}
        </div>
        {f && (
          <div>
            <div className="label micro">Uzun vade · bilanço</div>
            <div className="small">
              <span className={`chip s-${(VERDICT[f.verdict] || VERDICT.kosullu)[0]}`}>
                {(VERDICT[f.verdict] || VERDICT.kosullu)[1]}
              </span>
              <div className="fields two" style={{ marginTop: 10 }}>
                <Field label="İşletme">
                  {f.business_score != null ? `${Math.round(f.business_score)}/100` : "–"}
                </Field>
                <Field label="Değerleme">
                  {f.valuation_score != null ? `${Math.round(f.valuation_score)}/100` : "–"}
                </Field>
              </div>
              <div className="micro" style={{ marginTop: 8 }}>
                İki okuma ayrı vadeler içindir: bilanço kararı kısa vadeli sinyalin sonucunu değiştirmedi.
              </div>
            </div>
          </div>
        )}
      </div>

      {(joint.length > 1 || single) && (
        <Segments label="Algoritma" value={system.id} onChange={(k) => { setPick(k); setAll(false); }}
                  options={chips(single ? [...joint, ...singles] : joint)} />
      )}

      <div className="section-title" style={{ marginTop: 22 }}>
        {system.title} <span className="dim">· bu enstrümandaki işlemleri</span>
      </div>
      <div className="group group-pad">
        <div className="tiles four" style={{ marginBottom: 14 }}>
          <Tile label="Kapanan işlem" value={own.trades} format={count} />
          <Tile label="Kazanan" value={own.trades ? own.wins / own.trades : null} format={share}
                hint={own.trades ? `${own.wins} / ${own.trades}` : null} />
          <Tile label="İşlem başı net" value={own.net} format={(v) => pct(v, 2)} toneOf />
          <Tile label="İşlem başı R" value={own.r} format={(v) => inR(v)} toneOf
                hint={own.r != null ? `toplam ${inR(own.r * own.trades, 1)}, ${own.trades} işlemde` : null} />
        </div>
        <CandleChart key={system.id} prices={d.prices} trades={system.trades} through={d.through} />
        <div className="micro" style={{ marginTop: 8 }}>
          Yeşil mum: gün yükselişle kapandı; kırmızı: düşüşle. Renkli bantlar işlemlerdir (yeşil kazanç,
          kırmızı kayıp, mavi açık); kesikli çizgi açık pozisyonun stopudur. Fiyatlar bölünme ve temettüye
          göre düzeltilmiştir. {system.status === "marked" && "Bu kural 2022–25 döneminde tutmadı."}
        </div>
      </div>

      <div className="section-title" style={{ marginTop: 28 }}>
        İşlemler <span className="dim">· 2006'dan bugüne {system.trades.length}</span>
      </div>
      <div className="group">
        <div className="sigtrades sighead micro">
          <span>Alış</span><span>Satış</span><span>Gün</span><span>Nasıl kapandı</span>
          <span>Stop · risk</span><span>Net</span><span>R</span>
        </div>
        {rows.map((t, i) => (
          <div className="sigtrades small rise" style={{ "--i": i }} key={`${t.signal}-${i}`}>
            <span className="num">
              {t.entry ? <>{day(t.entry)} <span className="dim">· {price(t.entry_price)}</span></>
                : <span className="dim">yarın açılışta</span>}
            </span>
            <span className="num">
              {t.exit ? <>{day(t.exit)} <span className="dim">· {price(t.exit_price)}</span></>
                : t.entry ? <span className="dim">henüz satılmadı · son fiyat {price(t.exit_price)}</span>
                  : "–"}
            </span>
            <span className="num">{t.entry ? t.days : "–"}</span>
            <span>
              {t.exit ? reasonOf(t) : t.entry ? (t.closing ? "Açık · yarın satılır" : "Açık") : "Yeni sinyal"}
            </span>
            <span className="num">
              {t.stop == null ? "–"
                : <>{price(t.stop_now ?? t.stop)} <span className="dim">· {riskOf(t.risk)}</span></>}
            </span>
            <span className={`num s-${t.entry ? tone(t.net) : "neutral"}`}>{t.entry ? pct(t.net) : "–"}</span>
            <span className={`num s-${t.entry ? tone(t.r) : "neutral"}`}>{t.entry ? inR(t.r, 1) : "–"}</span>
          </div>
        ))}
        {system.trades.length > 10 && (
          <button className="listbtn more" onClick={() => setAll(!all)}>
            {all ? "Daha az göster" : `Tümünü göster (${system.trades.length})`}
          </button>
        )}
      </div>
      <div className="section-foot">
        Net: alış ve satış komisyonu düşülmüş sonuç. Risk: alış fiyatı ile stop arasındaki mesafe; bu mesafe
        1R'dir. Stop tam seviyesinde çalışırsa kayıp yaklaşık −1R olur; fiyat stopun altında açılırsa daha
        büyük olur ve "açılış boşluğu" diye yazılır.
      </div>

      {singles.length > 0 && (
        <button className="link" onClick={() => { setSingle(!single); setPick(null); }}
                style={{ margin: "18px 22px 0" }}>
          {single ? "Tek tek kuralları gizle" : `Tek tek kuralların işlemlerini de göster (${singles.length}) ›`}
        </button>
      )}
    </div>
  );
}

export default function Signals({ market, instrument, onMarket, onInstrument, onCompany }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [kind, setKind] = useState("all");
  const [tab, setTab] = useState("signals");
  const [algo, setAlgo] = useState(null);
  const [rules, setRules] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/signals?market=${market}`);
      const body = await r.json();
      if (!r.ok) { setError(body.detail || "yüklenemedi"); setD(null); }
      else { setD(body); setError(null); }
      return body;
    } catch (e) { setError(String(e)); return null; }
  }, [market]);

  useEffect(() => { setD(null); setAlgo(null); load(); }, [load]);

  // While the rebuild runs the file on disk is the old one; ask again until
  // the job is over, then read the new file.
  useEffect(() => {
    if (!d?.refreshing) return undefined;
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [d?.refreshing, load]);

  async function refresh() {
    try {
      const r = await fetch("/api/signals/refresh", { method: "POST" });
      const body = await r.json();
      if (!r.ok) setError(body.detail || "yenilenemedi");
      else load();
    } catch (e) { setError(String(e)); }
  }

  const markets = d?.markets || [
    { key: "sp500", label: "ABD hisseleri" }, { key: "etf", label: "Endeks ve ETF" },
    { key: "bist", label: "BIST" },
  ];

  if (instrument) {
    return (
      <>
        <button className="link" onClick={() => onInstrument(null)}>‹ {d?.label || "Sinyaller"}</button>
        <Journal market={market} instrument={instrument} onCompany={onCompany} />
      </>
    );
  }

  const joint = (d?.systems || []).filter((s) => s.combined);
  const hasJoint = joint.length > 0;
  const mine = (d?.signals || []).filter((s) => Boolean(s.combined) === hasJoint);
  const shown = mine.filter((s) => kind === "all" || s.state === kind);
  const counts = { pending: 0, open: 0 };
  for (const s of mine) counts[s.state] += 1;
  const listed = (d?.systems || []).filter((s) => !s.combined && s.status === "listed");
  const marked = (d?.systems || []).filter((s) => !s.combined && s.status === "marked");
  const current = joint.find((s) => s.id === algo) || joint[0];

  return (
    <>
      <Segments label="Piyasa" value={market} onChange={onMarket} options={markets} />

      {error && <div className="group group-pad small" style={{ marginTop: 16 }}>{error}</div>}
      {!d && !error && <div className="small dim" style={{ marginTop: 24 }}>Yükleniyor…</div>}

      {d && (
        <>
          <div className="subtabs">
            <Segments label="Görünüm" value={tab} onChange={setTab} className="filters underline"
                      options={[
                        { key: "signals", label: "Sinyaller", count: mine.length },
                        { key: "performance", label: "Performans" },
                        { key: "rules", label: "Kurallar" },
                      ]} />
            <span className="micro">
              {day(d.through)} kapanışı ·{" "}
              <button className="link" onClick={refresh} disabled={d.refreshing} style={{ fontSize: 12.5 }}>
                {d.refreshing ? "yenileniyor…" : "veriyi yenile"}
              </button>
            </span>
          </div>

          {tab === "signals" && (
            <div className="fade" key={`signals-${market}`}>
              <Verdict systems={joint} currency={d.currency} />
              <div className="micro" style={{ margin: "14px 22px 12px" }}>
                {hasJoint
                  ? "Algoritmanın bugün pozisyonda olduğu ya da yarın alacağı enstrümanlar. Hepsi alış yönlüdür: alınır, çıkış kuralı ya da stop gelince satılır. Açığa satış yoktur."
                  : "Bu piyasada koşulları sağlayan bir birleşik algoritma çıkmadı; liste tek tek kurallardandır."}
              </div>
              <Segments label="Durum" value={kind} onChange={setKind} options={[
                { key: "all", label: "Tümü", count: counts.pending + counts.open },
                { key: "pending", label: "Yeni sinyal", count: counts.pending },
                { key: "open", label: "Pozisyonda", count: counts.open },
              ]} />
              <div style={{ marginTop: 12 }}>
                {shown.length === 0 && (
                  <div className="group group-pad small dim">Şu an bu durumda enstrüman yok.</div>
                )}
                {shown.map((s, i) => (
                  <SignalCard key={`${s.instrument}-${s.system}`} s={s} d={d} index={i}
                              onOpen={onInstrument} />
                ))}
              </div>
              <div className="section-title" style={{ marginTop: 26 }}>Başka bir enstrümanın geçmişi</div>
              <select className="sigselect" value="" aria-label="Enstrüman seç"
                      onChange={(e) => e.target.value && onInstrument(e.target.value)}>
                <option value="">Bir enstrüman seç…</option>
                {d.instruments.map((x) => (
                  <option key={x.instrument} value={x.instrument}>
                    {x.instrument}{x.name !== x.instrument ? ` · ${x.name}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          {tab === "performance" && (
            <div className="fade" key={`performance-${market}`}>
              {!hasJoint && (
                <div className="group group-pad small dim">Bu piyasada birleşik algoritma yok.</div>
              )}
              {joint.length > 1 && (
                <Segments label="Algoritma" value={current.id} onChange={setAlgo}
                          options={joint.map((s) => ({ key: s.id, label: s.title }))} />
              )}
              {current && (
                <div style={{ marginTop: 12 }}>
                  <Verdict systems={[current]} currency={d.currency} />
                  <div style={{ height: 14 }} />
                  <Performance key={current.id} system={current} d={d} />
                </div>
              )}
            </div>
          )}

          {tab === "rules" && (
            <div className="fade" key={`rules-${market}`}>
              <div className="section-title">Algoritma <span className="dim">· {joint.length}</span></div>
              <div className="group">
                {joint.map((s) => <SystemCard key={s.id} system={s} startOpen cost={d.cost_per_side} />)}
                {joint.length === 0 && (
                  <div className="group-pad small dim">
                    Bu piyasada koşulları sağlayan bir birleşim çıkmadı (en az %45 kazanan, yılda en az 20
                    işlem, tek tek kurallardan iyi).
                  </div>
                )}
              </div>
              <div className="section-foot">
                Algoritma, aşağıdaki kuralların hepsine aynı gün bakar ve hangi sinyalin alınacağına tek bir
                ölçüyle karar verir. Tablodaki soluk satır, hiç seçim yapılmadan her sinyalin alınması
                hâlidir; aradaki fark birleştirmenin katkısıdır. 2006–2016'da öğrenildi, 2017–2021'de
                seçildi, 2022–2025 bir kez okundu. Maliyet tek yön
                %{(d.cost_per_side * 100).toFixed(2).replace(".", ",")}.
                {market === "bist" && " BIST sonuçları nominal liradır ve yalnızca bugün işlem gören şirketleri kapsar."}
              </div>

              <button className="link" onClick={() => setRules(!rules)} style={{ margin: "22px 22px 0" }}>
                {rules ? "Tek tek kuralları gizle" : `Tek tek kurallar (${listed.length + marked.length}) ›`}
              </button>
              {rules && (
                <div className="fade">
                  <div className="section-title" style={{ marginTop: 14 }}>
                    Üç dönemde de kâr edenler <span className="dim">· {listed.length}</span>
                  </div>
                  <div className="group">
                    {listed.map((s) => <SystemCard key={s.id} system={s} cost={d.cost_per_side} />)}
                    {listed.length === 0 && <div className="group-pad small dim">Yok.</div>}
                  </div>
                  {marked.length > 0 && (
                    <>
                      <div className="section-title" style={{ marginTop: 22 }}>
                        Son dönemde tutmayanlar <span className="dim">· {marked.length}</span>
                      </div>
                      <div className="group">
                        {marked.map((s) => <SystemCard key={s.id} system={s} cost={d.cost_per_side} />)}
                      </div>
                    </>
                  )}
                  <div className="section-foot">
                    Denenen {d.tried} kuraldan {d.shown} tanesi iki dönemde, {d.listed} tanesi üç dönemde de
                    işlem başına kâr etti. Tek başlarına sinyal listesinde yer almazlar; algoritmanın
                    girdisidirler.
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}
