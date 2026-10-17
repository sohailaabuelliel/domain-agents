# Evaluation report

Generated 2026-10-17 05:50.  Metric definitions: see docs/EVALUATION.md.

| Domain | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |
|---|---|---|---|---|---|---|---|
| hospitality | 10 | 100% | 83% | 0% | 100% | 17% | 11.1s |
| marketing | 10 | 100% | 100% | 0% | 100% | 0% | 12.7s |
| medical | 10 | 100% | 100% | 0% | 100% | 0% | 11.4s |
| pharma | 10 | 100% | 83% | 0% | 100% | 0% | 16.2s |
| finance | 10 | 100% | 100% | 0% | 100% | 0% | 12.4s |

## Misses (for debugging)

- **hospitality/hs-05** (answer) status=`no_evidence` — What do guests praise the most?  
   
- **pharma/ph-05** (answer) status=`answered` — What are the main warnings for amiodarone when used with warfarin?  
  Amiodarone is recognized as a medication that interacts with warfarin, and clinical literature suggests that coadministration should be avoided or closely monitored [S2][S3]. The provided sources do not specify the mechanism of the amiodarone-warfarin interaction or provide specific clinical management steps beyond the recommendation for close monitoring. Amiodarone and Warfarin Interaction Consis
