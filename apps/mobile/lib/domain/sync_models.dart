/// Sync protocol models mirroring the backend `/sync` contract
/// (`services/api/src/app/api/schemas.py` SyncChange / SyncPullResponse /
/// SyncOperation / SyncResultOut / SyncPushResponse).
library;

import 'enums.dart';

class SyncChange {
  const SyncChange({
    required this.entityType,
    required this.id,
    required this.version,
    required this.updatedAt,
    required this.data,
  });

  factory SyncChange.fromJson(Map<String, dynamic> json) => SyncChange(
        entityType: json['entity_type'] as String,
        id: json['id'] as String,
        version: (json['version'] as num).toInt(),
        updatedAt: DateTime.tryParse(json['updated_at'] as String) ?? DateTime.now(),
        data: (json['data'] as Map<String, dynamic>?) ?? const <String, dynamic>{},
      );

  final String entityType;
  final String id;
  final int version;
  final DateTime updatedAt;

  /// Raw entity payload (TaskOut / AgreementOut / CallOut serialization).
  final Map<String, dynamic> data;
}

class SyncPullResult {
  const SyncPullResult({
    required this.changes,
    required this.syncToken,
    required this.hasMore,
  });

  factory SyncPullResult.fromJson(Map<String, dynamic> json) => SyncPullResult(
        changes: (json['changes'] as List<dynamic>)
            .map((e) => SyncChange.fromJson(e as Map<String, dynamic>))
            .toList(),
        syncToken: json['sync_token'] as String,
        hasMore: json['has_more'] as bool? ?? false,
      );

  final List<SyncChange> changes;
  final String syncToken;
  final bool hasMore;
}

class SyncOperation {
  const SyncOperation({
    required this.entityType,
    required this.entityId,
    required this.operation,
    required this.idempotencyKey,
    this.version,
    this.payload = const <String, dynamic>{},
  });

  final SyncEntityType entityType;
  final String entityId;

  /// Wire value: `update` | `delete`.
  final String operation;
  final String idempotencyKey;
  final int? version;
  final Map<String, dynamic> payload;

  Map<String, dynamic> toJson() => {
        'entity_type': entityType.wire,
        'entity_id': entityId,
        'operation': operation,
        'idempotency_key': idempotencyKey,
        'version': version,
        'payload': payload,
      };
}

class SyncOpResult {
  const SyncOpResult({
    required this.entityType,
    required this.entityId,
    required this.status,
    this.version,
    this.serverVersion,
    this.message,
  });

  factory SyncOpResult.fromJson(Map<String, dynamic> json) => SyncOpResult(
        entityType: json['entity_type'] as String,
        entityId: json['entity_id'] as String,
        status: json['status'] as String,
        version: (json['version'] as num?)?.toInt(),
        serverVersion: (json['server_version'] as num?)?.toInt(),
        message: json['message'] as String?,
      );

  final String entityType;
  final String entityId;

  /// Wire value: `accepted` | `conflict` | `rejected`.
  final String status;
  final int? version;
  final int? serverVersion;
  final String? message;

  bool get isAccepted => status == 'accepted';
  bool get isConflict => status == 'conflict';
  bool get isRejected => status == 'rejected';
}

class SyncPushResult {
  const SyncPushResult({required this.results});

  factory SyncPushResult.fromJson(Map<String, dynamic> json) => SyncPushResult(
        results: (json['results'] as List<dynamic>)
            .map((e) => SyncOpResult.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  final List<SyncOpResult> results;
}

class SyncResult {
  const SyncResult({
    required this.pulled,
    required this.pushed,
    required this.conflicts,
    this.errorMessage,
  });

  final int pulled;
  final int pushed;
  final int conflicts;
  final String? errorMessage;
}