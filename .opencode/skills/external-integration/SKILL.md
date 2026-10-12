---
name: external-integration
description: Add a safe cross-platform adapter for calendar, reminders, notes, messaging, or CRM.
---

# External integration workflow

Use this skill when adding or changing an integration with an external app
or service.

## Required steps

1. Add or extend a port interface in the domain/application layer.
2. Implement a platform-specific or API-specific adapter.
3. Map the universal `ExternalAction` model to the target system.
4. Require explicit user confirmation before any write operation.
5. Return a delivery result:
   - created
   - failed
   - requires_user_action
   - duplicate
6. Store delivery status and target object ID where available.
7. Add tests with a mocked adapter; never call a real external service in CI.
8. Run:
   - `cd apps/mobile && flutter test`
   - `cd services/api && pytest tests/integrations`

## Safety rules

- Never send conversation audio or the full transcript unless the user
  explicitly selected that option.
- Send only the confirmed action and minimal necessary context.
- Support cancellation or deletion where the target system allows it.
- Handle permission denial without crashing.
- Make every adapter replaceable through dependency injection.

## Adapter template

```dart
abstract interface class CalendarPort {
  Future<DeliveryResult> createEvent(ConfirmedCommitment commitment);
}
```

```python
class CalendarPort(Protocol):
    async def create_event(self, action: ExternalAction) -> DeliveryResult: ...
```