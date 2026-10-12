---
name: mobile
description: Implement a Flutter feature for the agreement-capture mobile app across Android and iOS.
---

# Mobile feature workflow

Use this skill for any task that adds or changes a mobile screen, flow,
state controller, local storage model, or native integration.

## Required steps

1. Read the relevant feature folder under `apps/mobile/lib/features/`.
2. Identify the user flow and required permissions.
3. Define or update domain models first.
4. Create a Riverpod state controller/use case.
5. Build the UI with Flutter widgets only; do not place API, database,
   or platform-channel logic inside widgets.
6. Add platform-specific behavior only behind an interface.
7. Add widget tests and, where relevant, integration tests.
8. Run:
   - `cd apps/mobile && flutter analyze`
   - `cd apps/mobile && flutter test`

## Cross-platform checklist

- [ ] Android and iOS behavior considered
- [ ] Permissions requested contextually
- [ ] Permission-denied fallback implemented
- [ ] Date/time uses device locale and stored timezone
- [ ] No direct platform API call in feature code
- [ ] Empty, loading, error, and offline states handled

## Output

Before coding, provide:
- affected files
- domain model changes
- user flow
- permission requirements
- test plan