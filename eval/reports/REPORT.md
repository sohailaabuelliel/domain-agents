# Evaluation report

Generated 2026-10-17 05:38.  Metric definitions: see docs/EVALUATION.md.

| Domain | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |
|---|---|---|---|---|---|---|---|
| hospitality | 10 | 100% | 67% | 12% | 75% | 33% | 17.8s |
| marketing | 10 | 100% | 83% | 0% | 100% | 17% | 21.4s |
| medical | 10 | 100% | 83% | 0% | 100% | 17% | 16.9s |
| pharma | 10 | 100% | 67% | 0% | 100% | 17% | 9.7s |
| finance | 10 | 100% | 83% | 0% | 100% | 17% | 15.1s |

## Misses (for debugging)

- **hospitality/hs-04** (answer) status=`no_evidence` — What is the overall average guest rating?  
   
- **hospitality/hs-06** (answer) status=`no_evidence` — ما هي مواعيد تقديم الإفطار؟  
   
- **hospitality/hs-09** (no_evidence) status=`answered` — What is the price of the spa package?  
  This summary is based on sample data for the fictional Azure Bay Resort [S7, S12]. The provided sources do not mention the price of a spa package, with the only reference to a spa being the option to offer a spa credit as a proportional gesture when a stay is affected [S1]. The data is synthetic sample data for a fictional company [S7, S12]. Pricing lists, amenities catalogs, and spa package rates
- **marketing/mk-06** (answer) status=`no_evidence` — ما هي أفضل قناة تسويقية من حيث العائد؟  
   
- **medical/md-06** (answer) status=`no_evidence` — ما هي أعراض فقر الدم بنقص الحديد؟  
   
- **pharma/ph-05** (answer) status=`answered` — What are the main warnings for amiodarone when used with warfarin?  
  Amiodarone is recognized as a medication that interacts with warfarin, and clinical literature suggests that coadministration should be avoided or closely monitored [S2][S3]. The provided sources do not specify the mechanism of the amiodarone-warfarin interaction or provide specific clinical management steps beyond the recommendation for close monitoring. Amiodarone and Warfarin Interaction Consis
- **pharma/ph-06** (answer) status=`no_evidence` — ما هي التفاعلات المعروفة بين الوارفارين والفلوكونازول؟  
   
- **finance/fn-06** (answer) status=`no_evidence` — كيف تطورت إيرادات نفيديا خلال السنوات الخمس الأخيرة؟  
   
