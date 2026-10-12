---
name: privacy-review
description: Review changes that touch audio, transcripts, personal data, permissions, or external data sharing.
---

# Privacy review workflow

Use this skill before merging any change involving recordings, transcripts,
contacts, calendar data, LLM prompts, or third-party APIs.

## Checklist

- [ ] Minimum necessary data is collected.
- [ ] Audio and transcript access is authenticated and authorized.
- [ ] User can delete a conversation and associated audio.
- [ ] External sharing is explicit and scoped to confirmed actions.
- [ ] Logs do not contain raw audio, full transcripts, tokens, or secrets.
- [ ] LLM prompts are redacted or stored with consent.
- [ ] Permissions are requested only for the active feature.
- [ ] Data-retention period is defined.
- [ ] Cross-border or third-party processing is documented.

## Required output

State:
1. What personal data is processed.
2. Where it is stored.
3. Who can access it.
4. When it is deleted.
5. What is sent to third parties.