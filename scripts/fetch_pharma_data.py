"""Build the Pharma knowledge base from REAL public sources.

* openFDA drug labels  -> domains/pharma/knowledge/fda_<drug>.md   (official prescribing information, sectioned)
* PubMed abstracts     -> domains/pharma/knowledge/pubmed_<slug>.md (title, journal, year, PMID, abstract)

Usage:  python scripts/fetch_pharma_data.py
No API key needed (both services are free). Re-running overwrites the files.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "domains" / "pharma" / "knowledge"
OUT.mkdir(parents=True, exist_ok=True)

DRUGS = [
    "warfarin", "fluconazole", "clarithromycin", "simvastatin", "atorvastatin", "metformin",
    "ibuprofen", "amiodarone", "apixaban", "digoxin", "lisinopril", "clopidogrel",
    "omeprazole", "sertraline", "semaglutide",
]
# openFDA label field -> readable section title
SECTIONS = {
    "boxed_warning": "Boxed Warning",
    "indications_and_usage": "Indications and Usage",
    "contraindications": "Contraindications",
    "warnings_and_cautions": "Warnings and Precautions",
    "warnings": "Warnings",
    "drug_interactions": "Drug Interactions",
    "adverse_reactions": "Adverse Reactions",
    "mechanism_of_action": "Mechanism of Action",
    "pregnancy": "Pregnancy",
}
MAX_SECTION_CHARS = 3800

PUBMED = {
    "warfarin-fluconazole": "warfarin fluconazole interaction INR bleeding",
    "clarithromycin-simvastatin": "clarithromycin simvastatin rhabdomyolysis interaction",
    "metformin-renal": "metformin lactic acidosis renal impairment",
    "apixaban-vs-warfarin": "apixaban versus warfarin atrial fibrillation bleeding randomized",
    "amiodarone-warfarin": "amiodarone warfarin interaction",
    "semaglutide-cv": "semaglutide cardiovascular outcomes randomized trial",
}


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # openFDA prefixes each section with e.g. "7 DRUG INTERACTIONS 7.1 ..." — keep but trim noise
    return text


def fetch_label(client: httpx.Client, drug: str) -> dict | None:
    for q in (f'openfda.generic_name:"{drug}"', f"openfda.generic_name:{drug}"):
        r = client.get("https://api.fda.gov/drug/label.json", params={"search": q, "limit": 5})
        if r.status_code != 200:
            continue
        results = r.json().get("results", [])
        # prefer the label with the richest interaction section
        results.sort(key=lambda x: -len(" ".join(x.get("drug_interactions", [""]))))
        if results:
            return results[0]
    return None


def write_label(drug: str, label: dict) -> int:
    parts, n_sections = [], 0
    for key, title in SECTIONS.items():
        val = label.get(key)
        if not val:
            continue
        text = clean(" ".join(val))[:MAX_SECTION_CHARS]
        if len(text) < 40:
            continue
        parts.append(f"## {title}\n\n{text}\n")
        n_sections += 1
    brand = ", ".join((label.get("openfda", {}).get("brand_name") or [])[:3])
    eff = label.get("effective_time", "")
    front = (
        "---\n"
        f"title: FDA prescribing information — {drug}\n"
        f"entity: {drug}\n"
        "doc_type: fda_label\n"
        "source: openFDA drug label API (api.fda.gov/drug/label)\n"
        f"url: https://api.fda.gov/drug/label.json?search=openfda.generic_name:{drug}\n"
        f"brands: {brand}\n"
        f"label_effective: {eff}\n"
        "---\n\n"
    )
    (OUT / f"fda_{drug}.md").write_text(front + f"# {drug.title()} — FDA label\n\n" + "\n".join(parts), encoding="utf-8")
    return n_sections


def fetch_pubmed(client: httpx.Client, slug: str, term: str, n: int = 2) -> int:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    s = client.get(f"{base}/esearch.fcgi", params={"db": "pubmed", "term": term + " AND hasabstract", "retmax": n, "sort": "relevance", "retmode": "json"})
    ids = s.json()["esearchresult"]["idlist"]
    if not ids:
        return 0
    time.sleep(0.4)
    f = client.get(f"{base}/efetch.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    root = ET.fromstring(f.text)
    blocks = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        journal = art.findtext(".//Journal/Title") or ""
        year = art.findtext(".//PubDate/Year") or (art.findtext(".//PubDate/MedlineDate") or "")[:4]
        abstract = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
        blocks.append(f"## PMID {pmid}: {title}\n\n{journal} ({year}). PMID: {pmid}\n\n{clean(abstract)}\n")
    front = (
        "---\n"
        f"title: PubMed abstracts — {term}\n"
        f"entity: {slug}\n"
        "doc_type: pubmed\n"
        "source: PubMed E-utilities (eutils.ncbi.nlm.nih.gov)\n"
        f"url: https://pubmed.ncbi.nlm.nih.gov/?term={term.replace(' ', '+')}\n"
        "---\n\n"
    )
    (OUT / f"pubmed_{slug}.md").write_text(front + "\n".join(blocks), encoding="utf-8")
    return len(blocks)


def main() -> None:
    with httpx.Client(timeout=40, headers={"User-Agent": "domain-agent-assignment/1.0"}) as c:
        for d in DRUGS:
            label = fetch_label(c, d)
            if not label:
                print(f"[FDA] {d}: NOT FOUND")
                continue
            print(f"[FDA] {d}: {write_label(d, label)} sections")
            time.sleep(0.3)
        for slug, term in PUBMED.items():
            print(f"[PubMed] {slug}: {fetch_pubmed(c, slug, term)} abstracts")
            time.sleep(0.5)
    total = sum(p.stat().st_size for p in OUT.glob("*.md"))
    print(f"\nWrote {len(list(OUT.glob('*.md')))} files, {total/1024:.0f} KB -> {OUT}")


if __name__ == "__main__":
    main()
