# Evaluation report

Generated 2026-10-17 11:28.  Metric definitions: see docs/EVALUATION.md.

| Domain | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |
|---|---|---|---|---|---|---|---|
| hospitality | 10 | 100% | 83% | 0% | 100% | 0% | 12.4s |
| marketing | 10 | 100% | 100% | 0% | 100% | 0% | 11.7s |
| medical | 10 | 100% | 100% | 0% | 100% | 0% | 12.7s |
| pharma | 10 | 100% | 83% | 0% | 100% | 0% | 11.7s |
| finance | 10 | 100% | 100% | 0% | 100% | 0% | 21.8s |

## Misses (for debugging)

- **hospitality/hs-05** (answer) status=`answered` — What do guests praise the most?  
  This is sample data for a fictional resort, Azure Bay Resort. Based on the reviews, guests consistently praise several key aspects of their stay, including the friendly and helpful front-desk team, the breakfast buffet with great variety and fresh fruit, spotless rooms with excellent housekeeping, and the convenient short walk to beach access with lovely views [S1, S2, S3, S4, S5, S6]. The data is
- **pharma/ph-05** (answer) status=`answered` — What are the main warnings for amiodarone when used with warfarin?  
  Literature indicates that coadministration of amiodarone with warfarin should be avoided or closely monitored due to consistent reports of interactions [S1]. The provided sources do not specify the exact mechanism, magnitude, or specific warnings regarding amiodarone beyond noting that coadministration should be avoided or closely monitored. Amiodarone and Warfarin Interaction Warning Consistent r
