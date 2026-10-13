/// Infrastructure/API error surface. The Application/UI layers map [ApiErrorKind]
/// to user-facing messages; no Dio types leak out of this layer.
library;

enum ApiErrorKind {
  network,
  unauthorized,
  forbidden,
  notFound,
  validation,
  conflict,
  server,
  sessionExpired,
  unknown,
}

class ApiException implements Exception {
  const ApiException(this.kind, this.message, {this.statusCode, this.data});

  final ApiErrorKind kind;
  final String message;
  final int? statusCode;
  final Object? data;

  bool get isRetryable =>
      kind == ApiErrorKind.network || kind == ApiErrorKind.server;

  @override
  String toString() =>
      'ApiException(${kind.name}${statusCode == null ? '' : ', $statusCode'}): $message';
}