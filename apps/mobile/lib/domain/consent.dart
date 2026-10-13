import 'enums.dart';

/// Version of the consent text the user agreed to. The server stores the same
/// version (`CONSENT_VERSION = "v1"` in `services/api`); bump it when the text
/// changes so the app re-asks instead of treating an old agreement as valid.
const String consentTextVersion = 'v1';

/// The app user's recording / AI-consent decision, cached locally.
///
/// The server is the source of truth (`consents` table), but it has no read
/// endpoint for the app-level consent, so the decision is persisted on the
/// device and written through on change. `synced` is false while a local
/// decision has not been accepted by the server yet (offline-first).
class AppConsent {
  const AppConsent({
    this.textVersion = consentTextVersion,
    this.status,
    this.synced = false,
  });

  factory AppConsent.fromJson(Map<String, dynamic> json) {
    final rawStatus = json['status'] as String?;
    return AppConsent(
      textVersion: (json['text_version'] as String?) ?? consentTextVersion,
      status: rawStatus == null ? null : ConsentStatus.fromWire(rawStatus),
      synced: (json['synced'] as bool?) ?? false,
    );
  }

  /// Fresh install: the user has not decided yet.
  static const AppConsent undecided = AppConsent();

  final String textVersion;

  /// `null` until the user decides; otherwise granted/denied/withdrawn.
  final ConsentStatus? status;

  /// True once the server accepted the decision (or it was restored from a
  /// cache of an accepted decision).
  final bool synced;

  bool get decided => status != null;

  /// Recording may only start when the user granted app consent
  /// (no-consent calls are ordinary calls with manual entry).
  bool get recordingEnabled => status == ConsentStatus.granted;

  /// The consent text changed since the decision → ask again.
  bool needsReconsent(String currentVersion) =>
      decided && textVersion != currentVersion;

  AppConsent copyWith({
    String? textVersion,
    ConsentStatus? status,
    bool? synced,
  }) {
    return AppConsent(
      textVersion: textVersion ?? this.textVersion,
      status: status ?? this.status,
      synced: synced ?? this.synced,
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
        'text_version': textVersion,
        'status': status?.wire,
        'synced': synced,
      };
}