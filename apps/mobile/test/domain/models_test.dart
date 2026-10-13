import 'package:agreement_capture/domain/enums.dart';
import 'package:agreement_capture/domain/models.dart';
import 'package:agreement_capture/domain/sync_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('TaskItem', () {
    test('parses the /me/tasks payload', () {
      final task = TaskItem.fromJson(<String, dynamic>{
        'id': 't1',
        'title': 'Позвонить клиенту',
        'description': null,
        'assignee_user_id': 'u1',
        'agreement_id': null,
        'due_date': '2026-10-15',
        'due_time': '09:00:00',
        'priority': 'high',
        'status': 'in_progress',
        'completed_at': null,
        'version': 3,
        'created_at': '2026-10-01T10:00:00Z',
        'updated_at': '2026-10-02T10:00:00Z',
      });
      expect(task.priority, TaskPriority.high);
      expect(task.status, TaskStatus.inProgress);
      expect(task.dueDate?.year, 2026);
      expect(task.dueDate?.month, 10);
      expect(task.version, 3);
    });

    test('parses a sync delta that omits version/created_at', () {
      final task = TaskItem.fromJson(<String, dynamic>{
        'id': 't1',
        'title': 'Позвонить',
        'assignee_user_id': 'u1',
        'priority': 'low',
        'status': 'new',
      });
      expect(task.version, 0);
      expect(task.dueDate, isNull);
      expect(task.priority, TaskPriority.low);
    });

    test('round-trips through toJson', () {
      final original = TaskItem(
        id: 't1',
        title: 'Позвонить',
        assigneeUserId: 'u1',
        priority: TaskPriority.medium,
        status: TaskStatus.done,
        dueDate: DateTime(2026, 10, 15),
        dueTime: '09:00:00',
        version: 2,
      );
      final restored = TaskItem.fromJson(original.toJson());
      expect(restored.id, original.id);
      expect(restored.status, original.status);
      expect(restored.dueDate, DateTime(2026, 10, 15));
      expect(restored.version, 2);
    });
  });

  group('Agreement', () {
    test('parses the agreement payload', () {
      final agreement = Agreement.fromJson(<String, dynamic>{
        'id': 'a1',
        'call_id': 'c1',
        'owner': 'counterparty',
        'owner_user_id': null,
        'type': 'payment',
        'title': 'Оплатить счёт',
        'object': 'Счёт №5',
        'due_date': '2026-10-20',
        'due_time': null,
        'amount': 15000.5,
        'currency': 'RUB',
        'source_quote': 'оплачу до двадцатого',
        'audio_start': 10.0,
        'audio_end': 14.5,
        'confidence': 0.91,
        'status': 'requires_review',
        'version': 1,
        'created_at': '2026-10-01T10:00:00Z',
        'updated_at': '2026-10-01T10:00:00Z',
      });
      expect(agreement.owner, AgreementOwner.counterparty);
      expect(agreement.status, AgreementStatus.requiresReview);
      expect(agreement.amount, 15000.5);
      expect(agreement.dueDate?.day, 20);
    });
  });

  group('sync models', () {
    test('parses a pull response', () {
      final page = SyncPullResult.fromJson(<String, dynamic>{
        'changes': <dynamic>[
          <String, dynamic>{
            'entity_type': 'task',
            'id': 't1',
            'version': 4,
            'updated_at': '2026-10-03T10:00:00Z',
            'data': <String, dynamic>{'id': 't1', 'title': 'X'},
          },
        ],
        'sync_token': 'tok',
        'has_more': true,
      });
      expect(page.changes, hasLength(1));
      expect(page.changes.single.entityType, 'task');
      expect(page.changes.single.version, 4);
      expect(page.hasMore, isTrue);
      expect(page.syncToken, 'tok');
    });

    test('parses a push response with conflict metadata', () {
      final result = SyncPushResult.fromJson(<String, dynamic>{
        'results': <dynamic>[
          <String, dynamic>{
            'entity_type': 'task',
            'entity_id': 't1',
            'status': 'conflict',
            'version': null,
            'server_version': 7,
            'message': 'version conflict',
          },
        ],
      });
      final op = result.results.single;
      expect(op.isConflict, isTrue);
      expect(op.serverVersion, 7);
    });
  });

  group('enums', () {
    test('map wire values and fall back safely', () {
      expect(Role.fromWire('manager'), Role.manager);
      expect(Role.fromWire('nonsense'), Role.user);
      expect(TaskStatus.fromWire('done'), TaskStatus.done);
      expect(SyncEntityType.tryFromWire('reminder'), SyncEntityType.reminder);
      expect(SyncEntityType.tryFromWire('nope'), isNull);
    });
  });
}
