"""Generate the SAMPLE knowledge bases for Marketing and Hospitality.

There is no public dataset for a brand's campaign results or a hotel's guest reviews, so these are
SYNTHETIC (seeded, reproducible) and every file says so in its front-matter and first line. All summary
statistics are COMPUTED from the generated records, so evaluation questions have verifiable answers.

Usage: python scripts/generate_sample_data.py
"""
from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1] / "domains"
NOTE = "SYNTHETIC SAMPLE DATA created for this assignment — fictional company, not real figures."


def front(title: str, entity: str, doc_type: str, source: str) -> str:
    return f"---\ntitle: {title}\nentity: {entity}\ndoc_type: {doc_type}\nsource: {source}\nurl: \n---\n\n"


# =====================================================================================  MARKETING
def marketing() -> None:
    out = ROOT / "marketing" / "knowledge"; out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(2026)
    brand = "Nile Glow Skincare"
    # channel -> (monthly spend base, CPM-ish, ctr, cvr, aov) ; designed patterns:
    ch = {"Instagram Ads": (14000, 9.0, 0.014, 0.021, 38), "TikTok Ads": (9000, 5.5, 0.020, 0.012, 33),
          "Google Search": (12000, 14.0, 0.045, 0.048, 41), "Email": (2500, 6.0, 0.032, 0.062, 47),
          "Influencer": (8000, 11.0, 0.017, 0.033, 44)}
    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    rec: dict[tuple, dict] = {}
    for mi, m in enumerate(months):
        for c, (spend0, cpm, ctr, cvr, aov) in ch.items():
            seas = 1.0 + (0.25 if m == "2026-03" else 0) + 0.06 * mi
            drift = 1.0
            if c == "TikTok Ads" and mi >= 3:   # creative fatigue: CTR drops after April
                ctr *= 0.78
            if c == "Instagram Ads" and m == "2026-05":  # Ramadan-season creative boost
                ctr *= 1.25
            spend = spend0 * seas * rnd.uniform(0.95, 1.05)
            impr = spend / cpm * 1000
            clicks = impr * ctr * rnd.uniform(0.95, 1.05)
            orders = clicks * cvr * rnd.uniform(0.93, 1.07)
            rev = orders * aov * rnd.uniform(0.97, 1.03)
            rec[(m, c)] = dict(spend=spend, impr=impr, clicks=clicks, orders=orders, rev=rev)
    # --- monthly performance tables (one doc per channel)
    for c in ch:
        rows = "| Month | Spend | Impressions | Clicks | CTR | Orders | Conv. rate | Revenue | ROAS | CPA |\n|---|---|---|---|---|---|---|---|---|---|\n"
        for m in months:
            r = rec[(m, c)]
            rows += (f"| {m} | ${r['spend']:,.0f} | {r['impr']:,.0f} | {r['clicks']:,.0f} | {r['clicks'] / r['impr'] * 100:.2f}% | {r['orders']:,.0f} | "
                     f"{r['orders'] / r['clicks'] * 100:.2f}% | ${r['rev']:,.0f} | {r['rev'] / r['spend']:.2f} | ${r['spend'] / r['orders']:.2f} |\n")
        tot = {k: sum(rec[(m, c)][k] for m in months) for k in ("spend", "impr", "clicks", "orders", "rev")}
        text = front(f"{brand} — {c} performance Jan–Jun 2026", c.lower().replace(" ", "-"), "sample_data", NOTE)
        text += f"# {c} — monthly performance\n\n_{NOTE}_\n\n## {c} — monthly table\n\n{rows}\n"
        text += (f"## {c} — six-month totals\n\nSpend ${tot['spend']:,.0f}; revenue ${tot['rev']:,.0f}; ROAS {tot['rev'] / tot['spend']:.2f}; "
                 f"blended CPA ${tot['spend'] / tot['orders']:.2f}; CTR {tot['clicks'] / tot['impr'] * 100:.2f}%; conversion rate {tot['orders'] / tot['clicks'] * 100:.2f}%.\n")
        (out / f"channel_{c.lower().replace(' ', '_')}.md").write_text(text, encoding="utf-8")
    # --- cross-channel ranking, computed
    ranking = sorted(ch, key=lambda c: -sum(rec[(m, c)]["rev"] for m in months) / sum(rec[(m, c)]["spend"] for m in months))
    body = "| Rank | Channel | Spend | Revenue | ROAS | CPA |\n|---|---|---|---|---|---|\n"
    for i, c in enumerate(ranking, 1):
        sp = sum(rec[(m, c)]["spend"] for m in months); rv = sum(rec[(m, c)]["rev"] for m in months); od = sum(rec[(m, c)]["orders"] for m in months)
        body += f"| {i} | {c} | ${sp:,.0f} | ${rv:,.0f} | {rv / sp:.2f} | ${sp / od:.2f} |\n"
    tik = [rec[(m, "TikTok Ads")] for m in months]
    ctr_by = [t["clicks"] / t["impr"] * 100 for t in tik]
    text = front(f"{brand} — channel ranking by ROAS (H1 2026)", "channel-ranking", "sample_data", NOTE)
    text += f"# Channel ranking H1 2026\n\n_{NOTE}_\n\n## Channels ranked by return on ad spend (ROAS)\n\n{body}\nROAS = revenue / ad spend. CPA = spend / orders.\n\n"
    text += (f"## TikTok Ads creative fatigue\n\nTikTok Ads click-through rate fell from {ctr_by[2]:.2f}% in {months[2]} to {ctr_by[3]:.2f}% in {months[3]} and stayed lower "
             f"({ctr_by[4]:.2f}% in {months[4]}, {ctr_by[5]:.2f}% in {months[5]}) after the spring creatives ran for more than ten weeks. The team attributes this to creative fatigue.\n")
    ig = rec[("2026-05", "Instagram Ads")]; ig4 = rec[("2026-04", "Instagram Ads")]
    text += (f"\n## Instagram Ads Ramadan creative lift\n\nIn {months[4]} the Ramadan-themed creatives lifted Instagram Ads CTR to {ig['clicks'] / ig['impr'] * 100:.2f}% "
             f"from {ig4['clicks'] / ig4['impr'] * 100:.2f}% in {months[3]}.\n")
    (out / "channel_ranking.md").write_text(text, encoding="utf-8")
    # --- hand-written campaign briefs and playbook
    camps = [("Hydra Serum Launch", "2026-02", "Instagram Ads + Influencer", "Launch the Hydra Serum to women 22-35 in Cairo and Alexandria", "Influencer-led unboxing reels outperformed static product posts by roughly 2x on saves.", "Total launch revenue was driven mostly by influencer-referred discount codes."),
             ("Spring Glow Sale", "2026-03", "Email + Google Search", "Seasonal discount (20%) to the existing customer list", "The segmented email to previous buyers converted far better than the all-subscribers blast.", "Search brand terms captured the demand created by email."),
             ("TikTok Routine Challenge", "2026-04", "TikTok Ads", "Reach new 18-24 audiences with a 30-day skincare routine challenge", "Reach was strong but conversion stayed low; the audience browses more than it buys.", "Creative was not refreshed, and fatigue appeared in May."),
             ("Ramadan Glow Gift Sets", "2026-05", "Instagram Ads + Email", "Gift-set bundles for Ramadan and Eid", "Bundles raised average order value; Arabic-language creatives were more effective than English ones.", "Early-bird email two weeks before Ramadan drove the largest single-day revenue.")]
    for name, m, chs, goal, learn, note in camps:
        t = front(f"Campaign brief — {name}", name.lower().replace(" ", "-"), "sample_data", NOTE)
        t += f"# {name}\n\n_{NOTE}_\n\n## {name} — goal and channels\n\nMonth: {m}. Channels: {chs}. Goal: {goal}.\n\n## {name} — what we learned\n\n{learn} {note}\n"
        (out / f"campaign_{name.lower().replace(' ', '_')}.md").write_text(t, encoding="utf-8")
    play = front("Digital marketing metrics — playbook", "playbook", "reference", "General industry knowledge written for this project (not company data)")
    play += """# Marketing metrics playbook

## Core metrics

CTR (click-through rate) = clicks / impressions. CVR (conversion rate) = orders / clicks. CPA = ad spend / orders. ROAS = revenue / ad spend. AOV = revenue / orders. CPM = cost per thousand impressions.

## Reading the metrics together

A high CTR with a low conversion rate usually means the ad attracts curiosity but the landing page or offer does not close. A falling CTR on an unchanged creative over many weeks is the classic sign of creative fatigue; the usual remedy is to rotate in new creative.

## Budget allocation

Shift budget gradually toward channels with the highest ROAS and lowest CPA, but keep some budget in upper-funnel channels that feed them. Test changes of about 10-20% at a time and judge on at least two weeks of data.

## Email

Email is cheap and high-converting because the audience already knows the brand. Segment by past behaviour; segmented sends typically beat all-subscriber blasts.

## Limits of these numbers

Attribution is imperfect: last-click credit favours search and email, while influencer and social channels often assist earlier in the journey.
"""
    (out / "playbook_marketing_metrics.md").write_text(play, encoding="utf-8")
    print("marketing files:", len(list(out.glob('*.md'))))


# =====================================================================================  HOSPITALITY
def hospitality() -> None:
    out = ROOT / "hospitality" / "knowledge"; out.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    hotel = "Azure Bay Resort (fictional)"
    topics = {
        "breakfast": ("The breakfast buffet had great variety and fresh fruit.", +1, 0.55),
        "staff": ("The front-desk team was friendly and very helpful.", +1, 0.55),
        "pool": ("The pool area was clean and the kids loved the slide.", +1, 0.40),
        "location": ("The beach access is a short walk and the view is lovely.", +1, 0.35),
        "ac": ("The air conditioning in our room was noisy and did not cool properly.", -1, 0.0),
        "checkin": ("Check-in took over 40 minutes and our room was not ready.", -1, 0.0),
        "wifi": ("The Wi-Fi kept disconnecting, impossible to work remotely.", -1, 0.0),
        "noise": ("We could hear the evening entertainment until after midnight.", -1, 0.0),
        "cleanliness": ("The room was spotless and the housekeeping excellent.", +1, 0.30),
        "price": ("Good value for the price, especially the half-board option.", +1, 0.25),
    }
    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
    reviews = []
    for m in months:
        n = rnd.randint(14, 18)
        for _ in range(n):
            bad = defaultdict(float)
            if m in ("2026-07", "2026-08"): bad["ac"] = 0.38       # heat wave => AC complaints
            if m in ("2026-03", "2026-04"): bad["checkin"] = 0.30  # peak-season check-in queues
            bad["wifi"] = 0.10; bad["noise"] = 0.08
            if m == "2026-05": bad["checkin"] = 0.05; bad["wifi"] = 0.04  # after process fixes
            picked = []
            for k, (txt, s, p) in topics.items():
                prob = p if s > 0 else bad.get(k, 0.04)
                if rnd.random() < prob: picked.append(k)
            neg = [k for k in picked if topics[k][1] < 0]; pos = [k for k in picked if topics[k][1] > 0]
            rating = max(1, min(5, round(4.3 + 0.25 * len(pos) - 0.95 * len(neg) + rnd.uniform(-0.5, 0.5))))
            if not picked: picked = ["staff"]; pos = ["staff"]
            reviews.append(dict(month=m, rating=rating, topics=picked, text=" ".join(topics[k][0] for k in picked), lang=rnd.choice(["en", "en", "en", "ar"])))
    # reviews files: one per month
    ar_map = {"breakfast": "البوفيه كان متنوع والفاكهة طازجة", "staff": "طاقم الاستقبال ودود ومتعاون جدًا", "pool": "حمام السباحة نظيف والأطفال استمتعوا", "location": "الشاطئ قريب والإطلالة جميلة",
              "ac": "التكييف في الغرفة مزعج ولا يبرد جيدًا", "checkin": "تسجيل الوصول استغرق أكثر من 40 دقيقة والغرفة لم تكن جاهزة", "wifi": "الواي فاي كان ينقطع باستمرار",
              "noise": "سمعنا ضوضاء الحفلات المسائية بعد منتصف الليل", "cleanliness": "الغرفة نظيفة جدًا والنظافة ممتازة", "price": "قيمة جيدة مقابل السعر"}
    for m in months:
        rs = [r for r in reviews if r["month"] == m]
        t = front(f"{hotel} — guest reviews {m}", f"reviews-{m}", "sample_data", NOTE)
        t += f"# Guest reviews {m}\n\n_{NOTE}_\n\n"
        for i, r in enumerate(rs, 1):
            txt = " ".join(ar_map[k] + "." for k in r["topics"]) if r["lang"] == "ar" else r["text"]
            t += f"## Review {m}-{i:02d} (rating {r['rating']}/5, {r['lang']})\n\n{txt}\n\n"
        (out / f"reviews_{m}.md").write_text(t, encoding="utf-8")
    # computed analytics
    by_m = defaultdict(list)
    for r in reviews: by_m[r["month"]].append(r)
    tbl = "| Month | Reviews | Average rating | Top complaint | Complaints about it |\n|---|---|---|---|---|\n"
    for m in months:
        rs = by_m[m]; negs = defaultdict(int)
        for r in rs:
            for k in r["topics"]:
                if topics[k][1] < 0: negs[k] += 1
        top = max(negs, key=negs.get) if negs else "none"
        tbl += f"| {m} | {len(rs)} | {mean(r['rating'] for r in rs):.2f} | {top} | {negs.get(top, 0)} |\n"
    totals = defaultdict(lambda: [0, 0])
    for r in reviews:
        for k in r["topics"]:
            totals[k][0 if topics[k][1] > 0 else 1] += 1
    praise = sorted(((k, v[0]) for k, v in totals.items() if topics[k][1] > 0), key=lambda x: -x[1])
    compl = sorted(((k, v[1]) for k, v in totals.items() if topics[k][1] < 0), key=lambda x: -x[1])
    overall = mean(r["rating"] for r in reviews)
    t = front(f"{hotel} — review analytics Jan–Aug 2026", "analytics", "sample_data", NOTE)
    t += f"# Review analytics\n\n_{NOTE}_\n\n## Monthly rating and top complaint\n\n{tbl}\nOverall average rating across {len(reviews)} reviews: {overall:.2f} / 5.\n\n"
    t += "## Most praised topics\n\n" + "\n".join(f"- {k}: {n} positive mentions" for k, n in praise) + "\n\n"
    t += "## Most frequent complaints\n\n" + "\n".join(f"- {k}: {n} complaints" for k, n in compl) + "\n"
    ac_m = {m: sum(1 for r in by_m[m] if "ac" in r["topics"]) for m in months}
    ci_m = {m: sum(1 for r in by_m[m] if "checkin" in r["topics"]) for m in months}
    def peaks(d: dict[str, int], k: int = 2) -> str:
        top = sorted(d.items(), key=lambda x: (-x[1], x[0]))[:k]
        return " and ".join(f"{m} ({n})" for m, n in top)
    t += (f"\n## Air-conditioning complaints by month\n\n" + ", ".join(f"{m}: {n}" for m, n in ac_m.items()) +
          f". The highest counts are in {peaks(ac_m, 1)}; the summer heat is the likely cause.\n\n"
          f"## Check-in delays by month\n\n" + ", ".join(f"{m}: {n}" for m, n in ci_m.items()) +
          f". The highest counts are in {peaks(ci_m)}.\n")
    (out / "analytics_reviews.md").write_text(t, encoding="utf-8")
    # policies / FAQ (hand-written)
    pol = front(f"{hotel} — policies and FAQ", "policies", "policy", NOTE)
    pol += f"""# Hotel policies and FAQ

_{NOTE}_

## Check-in and check-out

Check-in starts at 14:00 and check-out is at 12:00. Early check-in is subject to availability and is free before 14:00 only when the room is ready; late check-out until 16:00 costs 50% of the nightly rate.

## Cancellation policy

Free cancellation up to 72 hours before arrival. Within 72 hours, the first night is charged. Non-refundable rates cannot be cancelled or changed.

## Pool and beach hours

The main pool is open 07:00-20:00; the kids' pool closes at 18:00. The private beach is open 08:00-19:00 and lifeguards are on duty during those hours.

## Breakfast and dining

Breakfast is served 07:00-10:30 in the main restaurant. Half-board includes dinner between 19:00 and 22:00. Children under 6 eat free.

## Pets and smoking

Pets are not allowed. Smoking is permitted only on balconies and in the designated outdoor lounge.

## Service-recovery guidelines for complaints

Acknowledge the complaint within 24 hours, apologise sincerely, state the concrete action taken, and where the stay was affected offer a proportional gesture such as a room upgrade, a free dinner or a spa credit. Never argue with the guest in public replies. Escalate repeated complaints about the same issue to the operations manager.
"""
    (out / "policies_faq.md").write_text(pol, encoding="utf-8")
    print("hospitality files:", len(list(out.glob('*.md'))), "| reviews:", len(reviews), "| overall", round(overall, 2), "| ac by month", ac_m, "| checkin", ci_m)


if __name__ == "__main__":
    marketing()
    hospitality()
