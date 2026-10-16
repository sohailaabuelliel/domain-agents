"""Build the Finance knowledge base from REAL SEC EDGAR XBRL data (public company annual filings, 10-K).

For each company we write one markdown file with a 5-year table of reported figures and RATIOS THAT WE COMPUTE
(clearly labelled as computed, with the formula). Plus a short ratio glossary written by hand.

Usage: python scripts/fetch_finance_data.py      (no API key; SEC only requires a descriptive User-Agent)
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "domains" / "finance" / "knowledge"
OUT.mkdir(parents=True, exist_ok=True)
UA = "DomainAgentAssignment research-demo contact@example.com"

COMPANIES = {"apple": ("Apple Inc.", "0000320193"), "microsoft": ("Microsoft Corporation", "0000789019"),
             "tesla": ("Tesla, Inc.", "0001318605"), "amazon": ("Amazon.com, Inc.", "0001018724"),
             "nvidia": ("NVIDIA Corporation", "0001045810"), "walmart": ("Walmart Inc.", "0000104169")}

# label -> (candidate us-gaap concepts in priority order, kind)   kind: flow (duration) | stock (instant)
METRICS = {
    "Revenue": (["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"], "flow"),
    "Gross profit": (["GrossProfit"], "flow"),
    "Operating income": (["OperatingIncomeLoss"], "flow"),
    "Net income": (["NetIncomeLoss"], "flow"),
    "R&D expense": (["ResearchAndDevelopmentExpense"], "flow"),
    "Operating cash flow": (["NetCashProvidedByUsedInOperatingActivities"], "flow"),
    "Total assets": (["Assets"], "stock"),
    "Total liabilities": (["Liabilities"], "stock"),
    "Shareholders' equity": (["StockholdersEquity"], "stock"),
    "Cash & equivalents": (["CashAndCashEquivalentsAtCarryingValue"], "stock"),
}


def annual_series(facts: dict, concepts: list[str], kind: str) -> dict[int, float]:
    """fiscal-year-end year -> value. Companies switch XBRL concept names over time, so we MERGE all candidate
    concepts (earlier concept wins for a year) and de-duplicate by period end date (latest filing wins)."""
    merged: dict[int, float] = {}
    for concept in concepts:
        node = facts.get(concept)
        if not node:
            continue
        best: dict[str, tuple[str, float]] = {}
        for x in node["units"].get("USD", []):
            if x.get("form") not in ("10-K", "10-K/A"):
                continue
            if kind == "flow":
                if not x.get("start"):
                    continue
                days = (date.fromisoformat(x["end"]) - date.fromisoformat(x["start"])).days
                if not 340 <= days <= 380:
                    continue
            prev = best.get(x["end"])
            if prev is None or x["filed"] > prev[0]:
                best[x["end"]] = (x["filed"], float(x["val"]))
        for end, (_, v) in sorted(best.items()):
            merged.setdefault(int(end[:4]), v)   # labelled by the year the fiscal year ENDS (company convention)
    return dict(sorted(merged.items()))


def fmt(v: float | None) -> str:
    return "n/a" if v is None else f"${v / 1e9:,.1f}B"


def pct(a: float | None, b: float | None) -> str:
    return "n/a" if a is None or not b else f"{a / b * 100:.1f}%"


def write_company(slug: str, name: str, cik: str, client: httpx.Client) -> int:
    data = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").json()
    facts = data["facts"]["us-gaap"]
    series = {label: annual_series(facts, c, k) for label, (c, k) in METRICS.items()}
    years = sorted(set().union(*[set(s) for s in series.values()]))[-5:]
    rev, ni, gp, oi, assets, liab, eq = (series[k] for k in ("Revenue", "Net income", "Gross profit", "Operating income", "Total assets", "Total liabilities", "Shareholders' equity"))
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K"
    front = ("---\n" f"title: {name} — annual financials (SEC 10-K, XBRL)\n" f"entity: {slug}\n" "doc_type: sec_financials\n"
             "source: SEC EDGAR XBRL company facts (data.sec.gov), annual 10-K filings\n" f"url: {url}\n" "---\n\n")
    parts = [f"# {name}\n"]
    rows = "| Metric | " + " | ".join(f"FY{y}" for y in years) + " |\n|---|" + "---|" * len(years) + "\n"
    for label, s in series.items():
        if any(y in s for y in years):
            rows += f"| {label} | " + " | ".join(fmt(s.get(y)) for y in years) + " |\n"
    parts.append(f"## {name} — reported annual figures (USD billions)\n\nValues as reported in the company's 10-K filings. FY = fiscal year.\n\n{rows}")
    ratio = "| Ratio (computed) | " + " | ".join(f"FY{y}" for y in years) + " |\n|---|" + "---|" * len(years) + "\n"
    ratio += "| Revenue growth YoY | " + " | ".join("n/a" if (y - 1) not in rev or y not in rev else f"{(rev[y] / rev[y - 1] - 1) * 100:+.1f}%" for y in years) + " |\n"
    ratio += "| Gross margin | " + " | ".join(pct(gp.get(y), rev.get(y)) for y in years) + " |\n"
    ratio += "| Operating margin | " + " | ".join(pct(oi.get(y), rev.get(y)) for y in years) + " |\n"
    ratio += "| Net margin | " + " | ".join(pct(ni.get(y), rev.get(y)) for y in years) + " |\n"
    ratio += "| Return on equity | " + " | ".join(pct(ni.get(y), eq.get(y)) if eq.get(y) and eq[y] > 0 else "n/a" for y in years) + " |\n"
    ratio += "| Liabilities / assets | " + " | ".join(pct(liab.get(y), assets.get(y)) for y in years) + " |\n"
    parts.append(f"## {name} — profitability, growth and leverage ratios (computed from the figures above)\n\n"
                 "Computed by this project: growth = revenue / prior-year revenue − 1; margin = profit / revenue; ROE = net income / equity; leverage = liabilities / assets.\n\n" + ratio)
    last = years[-1]
    sents = []
    if last in rev and last - 1 in rev:
        sents.append(f"In FY{last} {name} reported revenue of {fmt(rev[last])}, {'up' if rev[last] >= rev[last - 1] else 'down'} {abs(rev[last] / rev[last - 1] - 1) * 100:.1f}% from {fmt(rev[last - 1])} in FY{last - 1}.")
    if last in ni:
        sents.append(f"Net income in FY{last} was {fmt(ni[last])} (net margin {pct(ni.get(last), rev.get(last))}).")
    if last in oi:
        sents.append(f"Operating income in FY{last} was {fmt(oi[last])} (operating margin {pct(oi.get(last), rev.get(last))}).")
    if sents:
        parts.append(f"## {name} — latest fiscal year in words\n\n" + " ".join(sents) + "\n")
    (OUT / f"sec_{slug}.md").write_text(front + "\n".join(parts), encoding="utf-8")
    return len(years)


GLOSSARY = """---
title: Financial ratios — definitions
entity: glossary
doc_type: glossary
source: Standard accounting definitions (written for this project)
url: https://www.investopedia.com/financial-ratios-4689817
---

# Financial ratios — definitions

## Gross margin

Gross margin = gross profit / revenue. It shows how much of each dollar of sales remains after the direct cost of producing goods or services. A higher gross margin means more pricing power or lower production cost.

## Operating margin

Operating margin = operating income / revenue. It measures profitability from core operations before interest and taxes, so it reflects how efficiently the business is run.

## Net margin

Net margin = net income / revenue. It is the share of revenue that ends up as profit after all expenses, interest and taxes.

## Return on equity (ROE)

ROE = net income / shareholders' equity. It shows how much profit a company generates for each dollar of equity. A very high ROE can also result from low equity after share buybacks, so it must be read together with leverage.

## Leverage (liabilities to assets)

Liabilities / assets shows what share of the company's assets is financed by debt and other obligations. Higher values mean higher financial risk if earnings fall.

## Revenue growth

Revenue growth = current-year revenue / prior-year revenue − 1. It shows how fast sales are expanding or shrinking.

## Operating cash flow

Cash generated by the core business during the year. It is harder to manipulate than net income, so strong operating cash flow that exceeds net income is generally a sign of earnings quality.
"""


def main() -> None:
    (OUT / "glossary_ratios.md").write_text(GLOSSARY, encoding="utf-8")
    with httpx.Client(timeout=60, headers={"User-Agent": UA}) as c:
        for slug, (name, cik) in COMPANIES.items():
            try:
                print(f"[SEC] {slug}: {write_company(slug, name, cik, c)} fiscal years")
            except Exception as e:  # noqa: BLE001
                print(f"[SEC] {slug}: FAILED {type(e).__name__} {e}")
            time.sleep(0.4)
    files = list(OUT.glob("*.md"))
    print(f"\nWrote {len(files)} files, {sum(p.stat().st_size for p in files) / 1024:.0f} KB -> {OUT}")


if __name__ == "__main__":
    main()
