---
name: commitment-extraction
description: Implement or modify LLM-based extraction of commitments from conversation transcripts.
---

# Commitment extraction workflow

Use this skill for transcript parsing, commitment schemas, prompt changes,
validation rules, confidence scoring, and date normalization.

## Required steps

1. Read existing Pydantic models in `services/api/app/domain/`.
2. Preserve the required fields:
   - type
   - title
   - owner
   - due_date
   - time
   - amount
   - currency
   - context_quote
   - audio_start
   - audio_end
   - confidence
   - status
3. Use Instructor with a Pydantic response model; do not parse raw JSON
   manually.
4. Add validation for impossible or ambiguous values.
5. Require a source quote and audio timestamps for every commitment.
6. Add unit tests using realistic Russian conversation snippets.
7. Run:
   - `cd services/api && pytest tests/domain tests/ml`
   - `cd services/api && ruff check .`
   - `cd services/api && mypy .`

## Extraction rules

- Extract only obligations explicitly stated or clearly implied by the
  conversation.
- Do not infer a deadline from vague phrases such as “скоро” or “на следующей
  неделе” unless the conversation gives enough context; otherwise use
  `needs_clarification`.
- Resolve relative dates using conversation date and user timezone.
- Separate a proposal from a confirmed agreement.
- Mark unknown ownership explicitly; never guess a person’s responsibility.

## Test cases to include

- Explicit deadline: “Я пришлю договор до пятницы.”
- Meeting with time: “Давайте созвонимся во вторник в 15:00.”
- Payment: “Оплату внесём до 20 числа.”
- Ambiguous phrase: “Постараемся сделать быстро.”
- Contradictory dates.
- No commitment present.