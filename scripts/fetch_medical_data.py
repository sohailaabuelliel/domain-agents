"""Build the Medical knowledge base from REAL public sources.

* MedlinePlus Health Topics (U.S. National Library of Medicine, public domain)  -> medlineplus_<topic>.md
* PubMed guideline / systematic-review abstracts                                  -> pubmed_<slug>.md

Usage: python scripts/fetch_medical_data.py      (no API key needed)
"""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "domains" / "medical" / "knowledge"
OUT.mkdir(parents=True, exist_ok=True)

TOPICS = {  # slug -> MedlinePlus search term
    "type2-diabetes": "type 2 diabetes", "hypertension": "high blood pressure", "asthma": "asthma",
    "heart-failure": "heart failure", "copd": "COPD", "chronic-kidney-disease": "chronic kidney disease",
    "hypothyroidism": "hypothyroidism", "iron-deficiency-anemia": "iron deficiency anemia", "migraine": "migraine",
    "depression": "depression", "pneumonia": "pneumonia", "osteoporosis": "osteoporosis",
    "urinary-tract-infection": "urinary tract infections", "atrial-fibrillation": "atrial fibrillation",
    "high-cholesterol": "high blood cholesterol",
}
PUBMED = {
    "hypertension-guideline": "hypertension guideline blood pressure target adults",
    "diabetes-standards": "type 2 diabetes management guideline glycemic target",
    "asthma-management": "asthma management guideline inhaled corticosteroid",
    "heart-failure-therapy": "heart failure guideline-directed medical therapy review",
}


def strip_tags(s: str) -> str:
    s = re.sub(r"<(br|/p|/li|/h\d)\s*/?>", "\n", s)
    s = re.sub(r"<li>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", html.unescape(s))).strip()


def fetch_topic(c: httpx.Client, slug: str, term: str) -> bool:
    r = c.get("https://wsearch.nlm.nih.gov/ws/query", params={"db": "healthTopics", "term": term, "retmax": 1, "rettype": "all"})
    root = ET.fromstring(r.text)
    doc = root.find(".//document")
    if doc is None:
        return False
    fields = {c_.get("name"): "".join(c_.itertext()) for c_ in doc.findall("content")}
    title = strip_tags(fields.get("title", term))
    summary = strip_tags(fields.get("FullSummary", fields.get("snippet", "")))
    if len(summary) < 200:
        return False
    url = doc.get("url", "")
    front = ("---\n" f"title: MedlinePlus — {title}\n" f"entity: {slug}\n" "doc_type: patient_health_topic\n"
             "source: MedlinePlus Health Topics, U.S. National Library of Medicine (public domain)\n" f"url: {url}\n" "---\n\n")
    # split the summary into paragraphs and group them under generic headings so chunks stay focused
    paras = [p.strip() for p in summary.split("\n") if p.strip()]
    body, buf, n = [f"# {title}\n"], [], 1
    for p in paras:
        buf.append(p)
        if sum(len(x) for x in buf) > 700:
            body.append(f"## {title} — part {n}\n\n" + "\n".join(buf) + "\n"); buf, n = [], n + 1
    if buf:
        body.append(f"## {title} — part {n}\n\n" + "\n".join(buf) + "\n")
    (OUT / f"medlineplus_{slug}.md").write_text(front + "\n".join(body), encoding="utf-8")
    return True


def fetch_pubmed(c: httpx.Client, slug: str, term: str, n: int = 3) -> int:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    ids = c.get(f"{base}/esearch.fcgi", params={"db": "pubmed", "term": term + " AND hasabstract AND (guideline[pt] OR review[pt])",
                                                "retmax": n, "sort": "relevance", "retmode": "json"}).json()["esearchresult"]["idlist"]
    if not ids:
        return 0
    time.sleep(0.4)
    root = ET.fromstring(c.get(f"{base}/efetch.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}).text)
    blocks = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        t = art.find(".//ArticleTitle")
        title = "".join(t.itertext()) if t is not None else ""
        journal = art.findtext(".//Journal/Title") or ""
        year = art.findtext(".//PubDate/Year") or (art.findtext(".//PubDate/MedlineDate") or "")[:4]
        abstract = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
        abstract = re.sub(r"\s+", " ", abstract).strip()
        blocks.append(f"## PMID {pmid}: {title}\n\n{journal} ({year}). PMID: {pmid}\n\n{abstract}\n")
    front = ("---\n" f"title: PubMed — {term}\n" f"entity: {slug}\n" "doc_type: pubmed\n"
             "source: PubMed E-utilities (eutils.ncbi.nlm.nih.gov)\n" f"url: https://pubmed.ncbi.nlm.nih.gov/?term={term.replace(' ', '+')}\n" "---\n\n")
    (OUT / f"pubmed_{slug}.md").write_text(front + "\n".join(blocks), encoding="utf-8")
    return len(blocks)


def main() -> None:
    with httpx.Client(timeout=40, headers={"User-Agent": "domain-agent-assignment/1.0"}) as c:
        for slug, term in TOPICS.items():
            print(f"[MedlinePlus] {slug}: {'ok' if fetch_topic(c, slug, term) else 'NOT FOUND'}")
            time.sleep(0.3)
        for slug, term in PUBMED.items():
            print(f"[PubMed] {slug}: {fetch_pubmed(c, slug, term)} abstracts")
            time.sleep(0.5)
    files = list(OUT.glob("*.md"))
    print(f"\nWrote {len(files)} files, {sum(p.stat().st_size for p in files) / 1024:.0f} KB -> {OUT}")


if __name__ == "__main__":
    main()
