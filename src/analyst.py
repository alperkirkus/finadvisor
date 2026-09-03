"""The interpretation layer: Claude reads the evidence package.

The division of labour is strict. `metrics.py` computes every number and
`report.py` assembles them; this module only asks the model what they mean.
The framework document is sent as a cached system prefix so repeated calls
pay for it once.
"""
import argparse
import json
import os
import sys
from typing import List, Literal, Optional

import anthropic
from pydantic import BaseModel, Field

import report

MODEL = "claude-opus-5"
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
KNOWLEDGE = os.path.join(os.path.dirname(__file__), "..", "knowledge",
                         "analysis-framework.md")

ROLE = """Sana bir sirketin hesaplanmis finansal kanit paketi verilecek.
Yukaridaki cerceveye gore yorumla.

Paketteki her sayi SEC EDGAR XBRL verisinden deterministik olarak
hesaplanmistir. Sen yorum katmanisin: sayi uretme, aritmetik yapma, paketin
disindaki hicbir bilgiyi (haber, fiyat, yonetim aciklamasi, sektor
soylentisi) kullanma.

Tum ciktiyi Turkce yaz. Metrik adlarini (roic, accrual_ratio gibi) ve skor
adlarini orijinal haliyle birak. Sayilari paketten aynen aktar."""


class RedFlag(BaseModel):
    signal: str = Field(description="Bayragin tek cumlelik tanimi")
    evidence: str = Field(description="Pakette hangi metrikler bunu gosteriyor, degerleriyle")
    severity: Literal["dusuk", "orta", "yuksek"]
    benign_explanation: Optional[str] = Field(
        description="Ayni veriyi aciklayabilecek zararsiz alternatif, varsa")


class WatchItem(BaseModel):
    metric: str
    confirms_thesis_if: str = Field(description="Hangi yone giderse tez dogrulanir")
    refutes_thesis_if: str = Field(description="Hangi yone giderse tez curur")


class AnalystReport(BaseModel):
    thesis: str = Field(description="Verinin en cok destekledigi okuma, 2-3 cumle")
    counter_thesis: str = Field(description="Ayni veriye bakan kuskucunun one cikaracagi sey. Zorunlu, bos birakma")
    profitability: str
    balance_sheet_health: str
    earnings_quality: str = Field(description="Kar nakde donuyor mu; accrual ve cash_conversion okumasi")
    score_reading: str = Field(description="F/Z''/M skorlarinin yorumu, her birinin yanilma modu belirtilerek")
    red_flags: List[RedFlag]
    trend_summary: str
    next_quarter_outlook: str = Field(description="Yalnizca mekanik olarak devam eden egilimler, kosullu aralik olarak")
    watch_items: List[WatchItem]
    confidence: Literal["dusuk", "orta", "yuksek"]
    confidence_rationale: str = Field(description="data_coverage, periods_available ve sektor uygulanabilirligine dayali gerekce")


def _load_env():
    """Reads a local .env so the key never has to live in the shell history.

    An already-exported variable wins, and an `ant auth login` profile is
    picked up by the SDK on its own when neither is present.
    """
    if not os.path.exists(ENV_FILE):
        return
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip("\"'")
        # The example file ships a literal placeholder. Letting it through
        # produces a 401 several layers away from the actual cause.
        if key.strip() == "ANTHROPIC_API_KEY" and not _is_real_key(val):
            # An empty or placeholder value must not shadow a real key that
            # is already exported in the environment.
            continue
        os.environ.setdefault(key.strip(), val)


def _is_real_key(val):
    return val.startswith("sk-ant-") and len(val) > 40 and "..." not in val


def analyze(pkg, effort="high"):
    _load_env()
    client = anthropic.Anthropic()
    framework = open(KNOWLEDGE, encoding="utf-8").read()

    # The framework never changes between companies, so it goes first and
    # carries the cache breakpoint; the package varies and goes after it.
    system = [
        {"type": "text", "text": framework,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": ROLE},
    ]
    user = ("Kanit paketi:\n\n```json\n"
            + json.dumps(pkg, indent=2, ensure_ascii=False, default=str)
            + "\n```")

    kwargs = dict(
        model=MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        output_format=AnalystReport,
    )
    try:
        resp = client.beta.messages.parse(
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **kwargs)
    except TypeError:
        # Older SDK without the scalar fallbacks form.
        resp = client.messages.parse(**kwargs)

    if resp.stop_reason == "refusal":
        raise SystemExit("Model istegi reddetti: %s" % resp.stop_details)
    return resp.parsed_output, resp.usage


def to_markdown(pkg, r):
    c = pkg["company"]
    out = ["# %s (%s) -- analiz" % (c["name"], c["ticker"]),
           "_%s itibariyle | %s | veri kapsami %.0f%%_"
           % (pkg["as_of"], c["industry"], pkg["data_coverage"] * 100),
           "\n## Tez\n" + r.thesis,
           "\n## Karsi tez\n" + r.counter_thesis,
           "\n## Karlilik\n" + r.profitability,
           "\n## Bilanco sagligi\n" + r.balance_sheet_health,
           "\n## Kar kalitesi\n" + r.earnings_quality,
           "\n## Skorlar\n" + r.score_reading,
           "\n## Trendler\n" + r.trend_summary]

    out.append("\n## Kirmizi bayraklar")
    if r.red_flags:
        for f in r.red_flags:
            out.append("- **[%s] %s**" % (f.severity, f.signal))
            out.append("  - Kanit: %s" % f.evidence)
            if f.benign_explanation:
                out.append("  - Zararsiz alternatif: %s" % f.benign_explanation)
    else:
        out.append("- Yok")

    out.append("\n## Gelecek ceyrek\n" + r.next_quarter_outlook)
    out.append("\n## Izlenecekler")
    for w in r.watch_items:
        out.append("- **%s** -- dogrular: %s | curutur: %s"
                   % (w.metric, w.confirms_thesis_if, w.refutes_thesis_if))

    out.append("\n## Guven: %s\n%s" % (r.confidence, r.confidence_rationale))
    out.append("\n> " + pkg["disclaimer"])
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Sirket icin AI finansal analiz raporu")
    ap.add_argument("ticker")
    ap.add_argument("--quarters", type=int, default=20)
    ap.add_argument("--effort", default="high",
                    choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--dry-run", action="store_true",
                    help="istegi olustur ama API'yi cagirma")
    ap.add_argument("--out", help="raporu bu dosyaya yaz")
    args = ap.parse_args()

    pkg = report.build(args.ticker, args.quarters)

    if args.dry_run:
        framework = open(KNOWLEDGE, encoding="utf-8").read()
        body = json.dumps(pkg, indent=2, ensure_ascii=False, default=str)
        print("model: %s | effort: %s" % (MODEL, args.effort))
        print("cerceve: %d karakter (cache'lenir)" % len(framework))
        print("kanit paketi: %d karakter" % len(body))
        print("\n--- kanit paketi ---\n" + body[:1500] + "\n...")
        return

    r, usage = analyze(pkg, args.effort)
    md = to_markdown(pkg, r)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(md)
        print("yazildi: %s" % args.out)
    else:
        print(md)
    print("\n---\ntoken: girdi %s (cache okuma %s, yazma %s), cikti %s"
          % (usage.input_tokens, usage.cache_read_input_tokens,
             usage.cache_creation_input_tokens, usage.output_tokens),
          file=sys.stderr)


if __name__ == "__main__":
    main()
