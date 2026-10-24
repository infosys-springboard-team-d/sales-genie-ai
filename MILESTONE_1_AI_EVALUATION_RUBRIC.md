# Milestone 1 AI Insight Evaluation — Proposed Rubric

**Status:** Requester reports that the team approved this rubric and the
associated 20-case dataset on 24 October 2026. The reviewer identity and
case-level score notes were not supplied.

**Approved set:** `resource/milestone_1_ai_evaluation_set.csv`  
**Set size:** 20 fictional records. At this denominator, 19 passing cases
equal 95%.

## Proposed case review

Review each record against only the supplied synthetic context and the saved
analysis for that same lead. Mark a case accurate only when all conditions pass:

1. **Summary grounded:** It reflects the company type and at least one material
   operational fact from the supplied notes, contains no contradiction, and
   presents no unsupplied company fact as verified.
2. **Need supported:** At least one potential need follows directly from the
   supplied problem or workflow; it does not introduce a new factual claim.
3. **Opportunity framed safely:** At least one opportunity is a plausible
   recommendation tied to the stated need, framed as a possibility rather than
   an existing capability, guaranteed result, or verified external fact.
4. **Qualification labeling:** The score is described as an estimate, not a
   conversion probability or proof of company quality.

An analysis case passes only if all four criteria pass. Otherwise, record the
failed criterion and a short reviewer note. A reviewer should mark uncertain
outputs as fail pending verification rather than infer facts.

## Proposed manageable-record check

A record is manageable only if lead creation succeeds, analysis is generated
for that lead, the analysis is saved, and a subsequent retrieval returns the
same analysis ID and lead ID.

## Proposed threshold interpretation

Report both rates separately:

- **Manageable records:** passing create/analyze/save/retrieve cases divided by
  20.
- **Accurate insights:** human-reviewed accurate cases divided by 20.

Each rate must be at least 95% (at least 19/20). The requester reports that the
team approved this interpretation and that both measures passed at 20/20.

## Review worksheet and reported outcome

`resource/milestone_1_ai_evaluation_results.json` contains generated model
outputs, operational checks, and the aggregate human-review result as reported
by the requester: 20/20 accurate (100%). Per-case reviewer identity, decisions,
and notes were not provided; the individual `manual_review` fields therefore
remain pending rather than being inferred from the aggregate score.
