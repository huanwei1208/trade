package io.tradedb.jdbc;

import java.io.UnsupportedEncodingException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;

final class TradeDbJdbcUrl {
  static final String URL_PREFIX = "jdbc:tradedb:";

  private final Path databasePath;
  private final boolean readOnly;
  private final boolean bootstrapCompat;
  private final int busyTimeoutMs;

  private TradeDbJdbcUrl(
      Path databasePath, boolean readOnly, boolean bootstrapCompat, int busyTimeoutMs) {
    this.databasePath = databasePath;
    this.readOnly = readOnly;
    this.bootstrapCompat = bootstrapCompat;
    this.busyTimeoutMs = busyTimeoutMs;
  }

  Path databasePath() {
    return databasePath;
  }

  boolean readOnly() {
    return readOnly;
  }

  boolean bootstrapCompat() {
    return bootstrapCompat;
  }

  int busyTimeoutMs() {
    return busyTimeoutMs;
  }

  static TradeDbJdbcUrl parse(String url, Properties info) throws SQLException {
    if (url == null || !url.startsWith(URL_PREFIX)) {
      throw new SQLException("Unsupported TradeDB JDBC URL: " + url);
    }

    String remainder = url.substring(URL_PREFIX.length());
    String pathPart = remainder;
    String queryPart = "";
    int queryIndex = remainder.indexOf('?');
    if (queryIndex >= 0) {
      pathPart = remainder.substring(0, queryIndex);
      queryPart = remainder.substring(queryIndex + 1);
    }

    if (pathPart.startsWith("//")) {
      pathPart = pathPart.substring(2);
    }

    Map<String, String> options = new LinkedHashMap<String, String>();
    options.putAll(parseQuery(queryPart));
    if (info != null) {
      for (String name : info.stringPropertyNames()) {
        options.put(normalizeKey(name), info.getProperty(name));
      }
    }

    boolean readOnly = parseBoolean(firstNonBlank(options, "readonly", "readOnly"), false);
    boolean bootstrapCompat =
        parseBoolean(firstNonBlank(options, "bootstrapcompat", "bootstrapCompat"), true);
    int busyTimeoutMs =
        parseInt(firstNonBlank(options, "busytimeoutms", "busyTimeoutMs", "busytimeout"), 30000);

    String rawDbPath = firstNonBlank(options, "dbpath", "dbPath");
    String rawDataRoot = firstNonBlank(options, "dataroot", "dataRoot");

    Path databasePath;
    if (isNonBlank(rawDbPath)) {
      databasePath = normalizePath(rawDbPath);
    } else if (isNonBlank(rawDataRoot)) {
      databasePath = resolveDatabasePath(normalizePath(rawDataRoot));
    } else if (isNonBlank(pathPart)) {
      Path candidate = normalizePath(pathPart);
      if (looksLikeDatabaseFile(pathPart)) {
        databasePath = candidate;
      } else {
        databasePath = resolveDatabasePath(candidate);
      }
    } else {
      databasePath = resolveDatabasePath(Paths.get("data").toAbsolutePath().normalize());
    }

    Path parent = databasePath.getParent();
    if (parent != null && !Files.exists(parent) && !readOnly) {
      try {
        Files.createDirectories(parent);
      } catch (Exception exc) {
        throw new SQLException("Failed to create TradeDB directory: " + parent, exc);
      }
    }
    if (readOnly && !Files.exists(databasePath)) {
      throw new SQLException(
          "TradeDB file does not exist for read-only connection: " + databasePath);
    }

    return new TradeDbJdbcUrl(databasePath, readOnly, bootstrapCompat, busyTimeoutMs);
  }

  private static Path resolveDatabasePath(Path dataRoot) {
    Path normalizedRoot = dataRoot.toAbsolutePath().normalize();
    Path newPath = normalizedRoot.resolve(".db").resolve("trade.db");
    if (Files.exists(newPath)) {
      return newPath;
    }
    Path legacyPath = normalizedRoot.resolve(".metadata").resolve("trade.db");
    if (Files.exists(legacyPath)) {
      return legacyPath;
    }
    return newPath;
  }

  private static Map<String, String> parseQuery(String query) throws SQLException {
    Map<String, String> values = new LinkedHashMap<String, String>();
    if (!isNonBlank(query)) {
      return values;
    }

    String[] pairs = query.split("&");
    for (String pair : pairs) {
      if (!isNonBlank(pair)) {
        continue;
      }
      int equals = pair.indexOf('=');
      String rawKey = equals >= 0 ? pair.substring(0, equals) : pair;
      String rawValue = equals >= 0 ? pair.substring(equals + 1) : "";
      values.put(normalizeKey(decode(rawKey)), decode(rawValue));
    }
    return values;
  }

  private static String decode(String value) throws SQLException {
    try {
      return URLDecoder.decode(value, StandardCharsets.UTF_8.name());
    } catch (UnsupportedEncodingException exc) {
      throw new SQLException("UTF-8 decoding is unavailable", exc);
    }
  }

  private static String normalizeKey(String key) {
    return key == null ? "" : key.trim().toLowerCase(Locale.ROOT);
  }

  private static String firstNonBlank(Map<String, String> options, String... keys) {
    for (String key : keys) {
      String value = options.get(normalizeKey(key));
      if (isNonBlank(value)) {
        return value;
      }
    }
    return null;
  }

  private static boolean parseBoolean(String value, boolean defaultValue) {
    if (!isNonBlank(value)) {
      return defaultValue;
    }
    String normalized = value.trim().toLowerCase(Locale.ROOT);
    if ("1".equals(normalized)
        || "true".equals(normalized)
        || "yes".equals(normalized)
        || "on".equals(normalized)) {
      return true;
    }
    if ("0".equals(normalized)
        || "false".equals(normalized)
        || "no".equals(normalized)
        || "off".equals(normalized)) {
      return false;
    }
    return defaultValue;
  }

  private static int parseInt(String value, int defaultValue) throws SQLException {
    if (!isNonBlank(value)) {
      return defaultValue;
    }
    try {
      return Integer.parseInt(value.trim());
    } catch (NumberFormatException exc) {
      throw new SQLException("Invalid integer property value: " + value, exc);
    }
  }

  private static boolean looksLikeDatabaseFile(String rawPath) {
    return rawPath != null && rawPath.toLowerCase(Locale.ROOT).endsWith(".db");
  }

  private static boolean isNonBlank(String value) {
    return value != null && !value.trim().isEmpty();
  }

  private static Path normalizePath(String rawPath) {
    String trimmed = rawPath.trim();
    if (trimmed.startsWith("~/")) {
      trimmed = System.getProperty("user.home") + trimmed.substring(1);
    }
    return Paths.get(trimmed).toAbsolutePath().normalize();
  }
}
