import 'enums.dart';

/// Immutable domain models mirroring the backend Pydantic schemas
/// (`services/api/src/app/api/schemas.py`). Parsing is lenient: unknown fields
/// are ignored, optional fields tolerate `null`.

DateTime? parseDate(String? raw) {
  if (raw == null) return null;
  final parsed = DateTime.tryParse(raw);
  return parsed?.toLocal();
}

String? formatDateOnly(DateTime? value) {
  if (value == null) return null;
  final local = value.toLocal();
  final m = local.month.toString().padLeft(2, '0');
  final d = local.day.toString().padLeft(2, '0');
  return '${local.year}-$m-$d';
}

class UserProfile {
  const UserProfile({
    required this.id,
    required this.phone,
    required this.fullName,
    required this.role,
    this.teamId,
    required this.timezone,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
        id: json['id'] as String,
        phone: json['phone'] as String,
        fullName: json['full_name'] as String,
        role: Role.fromWire(json['role'] as String),
        teamId: json['team_id'] as String?,
        timezone: json['timezone'] as String,
      );

  final String id;
  final String phone;
  final String fullName;
  final Role role;
  final String? teamId;
  final String timezone;
}

class AuthSession {
  const AuthSession({
    required this.accessToken,
    required this.refreshToken,
    required this.expiresIn,
    required this.user,
  });

  factory AuthSession.fromJson(Map<String, dynamic> json) => AuthSession(
        accessToken: json['access_token'] as String,
        refreshToken: json['refresh_token'] as String,
        expiresIn: (json['expires_in'] as num).toInt(),
        user: UserProfile.fromJson(json['user'] as Map<String, dynamic>),
      );

  factory AuthSession.fromStored(Map<String, dynamic> json) => AuthSession(
        accessToken: json['access_token'] as String,
        refreshToken: json['refresh_token'] as String,
        expiresIn: (json['expires_in'] as num?)?.toInt() ?? 0,
        user: UserProfile.fromJson(json['user'] as Map<String, dynamic>),
      );

  final String accessToken;
  final String refreshToken;
  final int expiresIn;
  final UserProfile user;

  Map<String, dynamic> toJson() => {
        'access_token': accessToken,
        'refresh_token': refreshToken,
        'expires_in': expiresIn,
        'user': {
          'id': user.id,
          'phone': user.phone,
          'full_name': user.fullName,
          'role': user.role.wire,
          'team_id': user.teamId,
          'timezone': user.timezone,
        },
      };
}

class TaskItem {
  const TaskItem({
    required this.id,
    required this.title,
    this.description,
    required this.assigneeUserId,
    this.agreementId,
    required this.priority,
    required this.status,
    this.dueDate,
    this.dueTime,
    this.completedAt,
    required this.version,
    this.createdAt,
    this.updatedAt,
  });

  factory TaskItem.fromJson(Map<String, dynamic> json) => TaskItem(
        id: json['id'] as String,
        title: json['title'] as String,
        description: json['description'] as String?,
        assigneeUserId: json['assignee_user_id'] as String,
        agreementId: json['agreement_id'] as String?,
        priority: TaskPriority.fromWire(json['priority'] as String),
        status: TaskStatus.fromWire(json['status'] as String),
        dueDate: parseDate(json['due_date'] as String?),
        dueTime: json['due_time'] as String?,
        completedAt: parseDate(json['completed_at'] as String?),
        version: (json['version'] as num?)?.toInt() ?? 0,
        createdAt: parseDate(json['created_at'] as String?),
        updatedAt: parseDate(json['updated_at'] as String?),
      );

  final String id;
  final String title;
  final String? description;
  final String assigneeUserId;
  final String? agreementId;
  final TaskPriority priority;
  final TaskStatus status;
  final DateTime? dueDate;
  final String? dueTime;
  final DateTime? completedAt;
  final int version;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'description': description,
        'assignee_user_id': assigneeUserId,
        'agreement_id': agreementId,
        'priority': priority.wire,
        'status': status.wire,
        'due_date': formatDateOnly(dueDate),
        'due_time': dueTime,
        'completed_at': completedAt?.toIso8601String(),
        'version': version,
        'created_at': createdAt?.toIso8601String(),
        'updated_at': updatedAt?.toIso8601String(),
      };
}

class Agreement {
  const Agreement({
    required this.id,
    required this.callId,
    required this.owner,
    required this.type,
    required this.title,
    this.object,
    this.dueDate,
    this.dueTime,
    this.amount,
    this.currency,
    required this.sourceQuote,
    required this.audioStart,
    required this.audioEnd,
    required this.confidence,
    required this.status,
    required this.version,
    this.createdAt,
    this.updatedAt,
  });

  factory Agreement.fromJson(Map<String, dynamic> json) => Agreement(
        id: json['id'] as String,
        callId: json['call_id'] as String,
        owner: AgreementOwner.fromWire(json['owner'] as String),
        type: json['type'] as String,
        title: json['title'] as String,
        object: json['object'] as String?,
        dueDate: parseDate(json['due_date'] as String?),
        dueTime: json['due_time'] as String?,
        amount: (json['amount'] as num?)?.toDouble(),
        currency: json['currency'] as String?,
        sourceQuote: json['source_quote'] as String,
        audioStart: (json['audio_start'] as num).toDouble(),
        audioEnd: (json['audio_end'] as num).toDouble(),
        confidence: (json['confidence'] as num).toDouble(),
        status: AgreementStatus.fromWire(json['status'] as String),
        version: (json['version'] as num?)?.toInt() ?? 0,
        createdAt: parseDate(json['created_at'] as String?),
        updatedAt: parseDate(json['updated_at'] as String?),
      );

  final String id;
  final String callId;
  final AgreementOwner owner;
  final String type;
  final String title;
  final String? object;
  final DateTime? dueDate;
  final String? dueTime;
  final double? amount;
  final String? currency;
  final String sourceQuote;
  final double audioStart;
  final double audioEnd;
  final double confidence;
  final AgreementStatus status;
  final int version;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  Map<String, dynamic> toJson() => {
        'id': id,
        'call_id': callId,
        'owner': owner.wire,
        'type': type,
        'title': title,
        'object': object,
        'due_date': formatDateOnly(dueDate),
        'due_time': dueTime,
        'amount': amount,
        'currency': currency,
        'source_quote': sourceQuote,
        'audio_start': audioStart,
        'audio_end': audioEnd,
        'confidence': confidence,
        'status': status.wire,
        'version': version,
        'created_at': createdAt?.toIso8601String(),
        'updated_at': updatedAt?.toIso8601String(),
      };
}

class Call {
  const Call({
    required this.id,
    required this.direction,
    required this.contactPhone,
    this.contactName,
    required this.status,
    this.startedAt,
    this.answeredAt,
    this.endedAt,
    this.recordingStartedAt,
    required this.version,
    this.createdAt,
    this.updatedAt,
  });

  factory Call.fromJson(Map<String, dynamic> json) => Call(
        id: json['id'] as String,
        direction: CallDirection.fromWire(json['direction'] as String),
        contactPhone: json['contact_phone'] as String,
        contactName: json['contact_name'] as String?,
        status: json['status'] as String,
        startedAt: parseDate(json['started_at'] as String?),
        answeredAt: parseDate(json['answered_at'] as String?),
        endedAt: parseDate(json['ended_at'] as String?),
        recordingStartedAt: parseDate(json['recording_started_at'] as String?),
        version: (json['version'] as num).toInt(),
        createdAt: parseDate(json['created_at'] as String?),
        updatedAt: parseDate(json['updated_at'] as String?),
      );

  final String id;
  final CallDirection direction;
  final String contactPhone;
  final String? contactName;
  final String status;
  final DateTime? startedAt;
  final DateTime? answeredAt;
  final DateTime? endedAt;
  final DateTime? recordingStartedAt;
  final int version;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  Map<String, dynamic> toJson() => {
        'id': id,
        'direction': direction.wire,
        'contact_phone': contactPhone,
        'contact_name': contactName,
        'status': status,
        'started_at': startedAt?.toIso8601String(),
        'answered_at': answeredAt?.toIso8601String(),
        'ended_at': endedAt?.toIso8601String(),
        'recording_started_at': recordingStartedAt?.toIso8601String(),
        'version': version,
        'created_at': createdAt?.toIso8601String(),
        'updated_at': updatedAt?.toIso8601String(),
      };
}

class ContactItem {
  const ContactItem({
    required this.id,
    required this.displayName,
    required this.phone,
  });

  final String id;
  final String displayName;
  final String phone;
}