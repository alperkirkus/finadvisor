// One registry describing how each engine metric should be read. `polarity`
// exists because a rising number is not always the better number -- accruals
// and leverage improve by falling, and the UI must not render those green.

export const PCT = "pct", MONEY = "money", RATIO = "ratio", MULT = "mult";

export const METRICS = {
  revenue_ttm:            { label: "Gelir (TTM)",          kind: MONEY, group: "Ölçek" },
  net_income_ttm:         { label: "Net kâr (TTM)",        kind: MONEY, group: "Ölçek" },
  ebitda_ttm:             { label: "FAVÖK (TTM)",          kind: MONEY, group: "Ölçek" },
  cfo_ttm:                { label: "İşletme nakit akışı",  kind: MONEY, group: "Ölçek" },
  fcf_ttm:                { label: "Serbest nakit akışı",  kind: MONEY, group: "Ölçek" },

  gross_margin:           { label: "Brüt marj",            kind: PCT, group: "Kârlılık" },
  operating_margin:       { label: "Faaliyet marjı",       kind: PCT, group: "Kârlılık" },
  net_margin:             { label: "Net marj",             kind: PCT, group: "Kârlılık" },
  fcf_margin:             { label: "Serbest nakit marjı",  kind: PCT, group: "Kârlılık" },
  roe:                    { label: "Özsermaye getirisi",   kind: PCT, group: "Kârlılık",
                            note: "Kaldıraçla şişer -- borçla birlikte oku" },
  roa:                    { label: "Aktif getirisi",       kind: PCT, group: "Kârlılık" },
  roic:                   { label: "Yatırılan sermaye getirisi", kind: PCT, group: "Kârlılık",
                            note: "Kalitenin en dürüst tek ölçüsü; sermaye maliyeti kabaca %8-10" },
  effective_tax_rate:     { label: "Efektif vergi oranı",  kind: PCT, group: "Kârlılık", polarity: "lower" },
  asset_turnover:         { label: "Aktif devir hızı",     kind: MULT, group: "Kârlılık" },
  equity_to_assets:       { label: "Özsermaye / varlık",   kind: PCT, group: "Bilanço",
                            note: "%10 altında ROE ve borç/özsermaye mekanik olarak bozulur" },

  total_debt:             { label: "Toplam borç",          kind: MONEY, group: "Bilanço", polarity: "lower" },
  net_debt:               { label: "Net borç",             kind: MONEY, group: "Bilanço", polarity: "lower" },
  working_capital:        { label: "İşletme sermayesi",    kind: MONEY, group: "Bilanço" },
  current_ratio:          { label: "Cari oran",            kind: MULT, group: "Bilanço" },
  quick_ratio:            { label: "Asit-test oranı",      kind: MULT, group: "Bilanço" },
  debt_to_equity:         { label: "Borç / özsermaye",     kind: MULT, group: "Bilanço", polarity: "lower" },
  net_debt_to_ebitda:     { label: "Net borç / FAVÖK",     kind: MULT, group: "Bilanço", polarity: "lower",
                            note: "Kamu hizmeti ve telekomda 4-5 yapısaldır" },
  interest_coverage:      { label: "Faiz karşılama",       kind: MULT, group: "Bilanço",
                            note: "2'nin altı kırılgan" },

  accrual_ratio:          { label: "Tahakkuk oranı",       kind: PCT, group: "Nakit kalitesi", polarity: "lower",
                            note: "Negatif iyidir -- nakit kârı aşıyor demektir" },
  cash_conversion:        { label: "Nakde dönüşüm",        kind: MULT, group: "Nakit kalitesi",
                            note: "CFO / net kâr; sürekli 0.8 altı uyarıdır" },

  revenue_growth_yoy:     { label: "Gelir büyümesi",       kind: PCT, group: "Büyüme" },
  net_income_growth_yoy:  { label: "Net kâr büyümesi",     kind: PCT, group: "Büyüme" },
  fcf_growth_yoy:         { label: "Serbest nakit büyümesi", kind: PCT, group: "Büyüme" },
};

export const GROUPS = ["Ölçek", "Kârlılık", "Bilanço", "Nakit kalitesi", "Büyüme"];

export function meta(key) {
  return METRICS[key] || { label: key, kind: RATIO, group: "Diğer" };
}

export function format(key, v) {
  if (v === null || v === undefined) return "--";
  const { kind } = meta(key);
  if (kind === MONEY) {
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(2) + " Mr$";
    if (a >= 1e6) return (v / 1e6).toFixed(0) + " M$";
    return v.toFixed(0);
  }
  if (kind === PCT) return (v * 100).toFixed(1) + "%";
  if (kind === MULT) return v.toFixed(2) + "×";
  return v.toFixed(2);
}

// Turns an engine direction into the status role the UI paints it with.
// `insufficient_history` is deliberately neutral rather than hidden.
export function directionStatus(direction) {
  if (direction === "improving") return { role: "good", icon: "▲", label: "iyileşiyor" };
  if (direction === "deteriorating") return { role: "critical", icon: "▼", label: "kötüleşiyor" };
  if (direction === "flat") return { role: "neutral", icon: "▬", label: "yatay" };
  return { role: "neutral", icon: "·", label: "yetersiz geçmiş" };
}

export const STATUS_VAR = {
  good: "var(--good)",
  warning: "var(--warning)",
  serious: "var(--serious)",
  critical: "var(--critical)",
  neutral: "var(--muted)",
};
