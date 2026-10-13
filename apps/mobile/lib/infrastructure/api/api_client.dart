import 'package:dio/dio.dart';

import '../../core/config.dart';
import 'api_exception.dart';

typedef AccessTokenReader = Future<String?> Function();
typedef TokenRefresher = Future<String?> Function();

/// Thin wrapper over Dio: base URL, JSON decoding, bearer auth, transparent
/// refresh-on-401 and mapping of transport errors to [ApiException].
class ApiClient {
  ApiClient({
    required String baseUrl,
    AccessTokenReader? accessToken,
    TokenRefresher? refreshToken,
    Duration? timeout,
  })  : _accessToken = accessToken,
        _refreshToken = refreshToken,
        _dio = Dio(
          BaseOptions(
            baseUrl: baseUrl,
            connectTimeout: timeout ?? AppConfig.requestTimeout,
            receiveTimeout: timeout ?? AppConfig.requestTimeout,
            sendTimeout: timeout ?? AppConfig.requestTimeout,
            headers: const {'Accept': 'application/json'},
          ),
        );

  final Dio _dio;
  final AccessTokenReader? _accessToken;
  final TokenRefresher? _refreshToken;

  Future<Object?> get(String path, {Map<String, Object?>? query, bool auth = true}) =>
      _send('GET', path, query: query, auth: auth);

  Future<Object?> post(String path, {Object? body, bool auth = true}) =>
      _send('POST', path, body: body, auth: auth);

  Future<Object?> patch(String path, {Object? body, bool auth = true}) =>
      _send('PATCH', path, body: body, auth: auth);

  Future<Object?> put(String path, {Object? body, bool auth = true}) =>
      _send('PUT', path, body: body, auth: auth);

  Future<Object?> delete(String path, {bool auth = true}) =>
      _send('DELETE', path, auth: auth);

  Future<Object?> _send(
    String method,
    String path, {
    Object? body,
    Map<String, Object?>? query,
    bool auth = true,
    bool retried = false,
  }) async {
    try {
      final headers = await _headers(auth);
      if (body != null) headers['Content-Type'] = 'application/json';
      final response = await _dio.request<Object?>(
        path,
        data: body,
        queryParameters: query,
        options: Options(method: method, headers: headers),
      );
      return response.data;
    } on DioException catch (error) {
      final status = error.response?.statusCode;
      if (auth && status == 401 && !retried && _refreshToken != null) {
        final renewed = await _refreshToken();
        if (renewed != null) {
          return _send(method, path, body: body, query: query, auth: auth, retried: true);
        }
        throw const ApiException(ApiErrorKind.sessionExpired, 'Session expired', statusCode: 401);
      }
      throw _mapError(error);
    }
  }

  Future<Map<String, String>> _headers(bool auth) async {
    if (!auth || _accessToken == null) return <String, String>{};
    final token = await _accessToken();
    if (token == null) return <String, String>{};
    return <String, String>{'Authorization': 'Bearer $token'};
  }

  ApiException _mapError(DioException error) {
    final status = error.response?.statusCode;
    final data = error.response?.data;
    final message = _extractMessage(data) ?? error.message ?? 'Request failed';
    final type = error.type;
    final isTransportFailure = type == DioExceptionType.connectionTimeout ||
        type == DioExceptionType.sendTimeout ||
        type == DioExceptionType.receiveTimeout ||
        type == DioExceptionType.connectionError ||
        type == DioExceptionType.badCertificate;
    if (isTransportFailure) {
      return ApiException(ApiErrorKind.network, message, statusCode: status, data: data);
    }
    if (status == null) {
      return ApiException(ApiErrorKind.network, message, data: data);
    }
    return ApiException(_kindForStatus(status), message, statusCode: status, data: data);
  }

  ApiErrorKind _kindForStatus(int status) {
    if (status == 401) return ApiErrorKind.unauthorized;
    if (status == 403) return ApiErrorKind.forbidden;
    if (status == 404) return ApiErrorKind.notFound;
    if (status == 409) return ApiErrorKind.conflict;
    if (status == 422) return ApiErrorKind.validation;
    if (status >= 500) return ApiErrorKind.server;
    return ApiErrorKind.unknown;
  }

  String? _extractMessage(Object? data) {
    if (data is Map) {
      final detail = data['detail'];
      if (detail is String) return detail;
      if (detail is Map && detail['message'] is String) return detail['message'] as String;
      if (data['message'] is String) return data['message'] as String;
      if (data['error'] is String) return data['error'] as String;
    }
    return null;
  }
}

Map<String, dynamic> asJsonMap(Object? data) {
  if (data is Map<String, dynamic>) return data;
  if (data is Map) return Map<String, dynamic>.from(data);
  throw const ApiException(ApiErrorKind.unknown, 'Expected a JSON object');
}

List<Map<String, dynamic>> asJsonList(Object? data) {
  if (data is List) {
    return data.whereType<Object?>().map((e) => asJsonMap(e)).toList();
  }
  throw const ApiException(ApiErrorKind.unknown, 'Expected a JSON array');
}