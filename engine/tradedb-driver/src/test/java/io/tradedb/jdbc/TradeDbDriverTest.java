package io.tradedb.jdbc;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.sqlite.JDBC;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TradeDbDriverTest {
    @TempDir
    Path tempDir;

    @Test
    void resolvesDataRootAndCreatesCompatibilityViews() throws Exception {
        Path dataRoot = tempDir.resolve("data-root");
        Path dbPath = dataRoot.resolve(".db").resolve("trade.db");
        seedDatabase(dbPath);

        Class.forName("io.tradedb.jdbc.TradeDbDriver");
        try (Connection connection = DriverManager.getConnection("jdbc:tradedb:" + dataRoot.toString());
             Statement statement = connection.createStatement()) {
            assertEquals(1, queryInt(statement, "SELECT COUNT(*) FROM signal_cache"));
            assertEquals("BK001", queryString(statement,
                "SELECT sector_code FROM instrument_sector_members WHERE symbol = '600000.SH'"));
            assertEquals("2026-03-12", queryString(statement,
                "SELECT end_date FROM downloads WHERE symbol = '600000.SH'"));
            assertEquals("2026-03-12", queryString(statement,
                "SELECT last_event_date FROM watermarks WHERE source = 'tushare_kline' AND dataset = 'daily' AND symbol = '600000.SH'"));
            assertEquals(23, queryInt(statement,
                "SELECT industry FROM meta_instruments WHERE symbol = '600000.SH'"));
        }
    }

    @Test
    void fallsBackToLegacyMetadataDirectory() throws Exception {
        Path dataRoot = tempDir.resolve("legacy-root");
        Path dbPath = dataRoot.resolve(".metadata").resolve("trade.db");
        seedDatabase(dbPath);

        Class.forName("io.tradedb.jdbc.TradeDbDriver");
        try (Connection connection = DriverManager.getConnection("jdbc:tradedb:" + dataRoot.toString());
             Statement statement = connection.createStatement()) {
            assertEquals(1, queryInt(statement, "SELECT COUNT(*) FROM events"));
        }
    }

    @Test
    void supportsReadOnlyModeAfterBootstrap() throws Exception {
        Path dataRoot = tempDir.resolve("readonly-root");
        Path dbPath = dataRoot.resolve(".db").resolve("trade.db");
        seedDatabase(dbPath);

        Class.forName("io.tradedb.jdbc.TradeDbDriver");
        try (Connection connection = DriverManager.getConnection(
            "jdbc:tradedb:" + dataRoot.toString() + "?readOnly=true");
             Statement statement = connection.createStatement()) {
            assertEquals(1, queryInt(statement, "SELECT COUNT(*) FROM signal_cache"));
            assertThrows(SQLException.class,
                () -> statement.executeUpdate("INSERT INTO settings(key, value, value_type, category) VALUES ('x', '1', 'string', 'test')"));
        }
    }

    private static void seedDatabase(Path dbPath) throws Exception {
        Files.createDirectories(dbPath.getParent());
        try (Connection connection = new JDBC().connect("jdbc:sqlite:" + dbPath.toAbsolutePath(), new Properties());
             Statement statement = connection.createStatement()) {
            statement.execute("CREATE TABLE signals(date TEXT, symbol TEXT)");
            statement.execute("INSERT INTO signals(date, symbol) VALUES ('2026-03-12', '600000.SH')");

            statement.execute("CREATE TABLE event_log(id INTEGER PRIMARY KEY, topic TEXT)");
            statement.execute("INSERT INTO event_log(id, topic) VALUES (1, 'job.completed')");

            statement.execute("CREATE TABLE market_events(event_id TEXT PRIMARY KEY, event_date TEXT, event_type TEXT)");
            statement.execute("INSERT INTO market_events(event_id, event_date, event_type) VALUES ('evt-1', '2026-03-12', 'macro')");

            statement.execute(
                "CREATE TABLE sector_members(symbol TEXT PRIMARY KEY, sector_code TEXT, sector_name TEXT, industry_code INTEGER, updated_at TEXT)"
            );
            statement.execute(
                "INSERT INTO sector_members(symbol, sector_code, sector_name, industry_code, updated_at) VALUES " +
                    "('600000.SH', 'BK001', '银行', 23, '2026-03-12 09:00:00')"
            );

            statement.execute(
                "CREATE TABLE instruments(symbol TEXT PRIMARY KEY, name TEXT, market INTEGER, market_name TEXT, board INTEGER, " +
                    "industry INTEGER, list_date TEXT, delist_date TEXT, status INTEGER, total_shares INTEGER, float_shares INTEGER)"
            );
            statement.execute(
                "INSERT INTO instruments(symbol, name, market, market_name, board, industry, list_date, delist_date, status, total_shares, float_shares) VALUES " +
                    "('600000.SH', '浦发银行', 0, 'Shanghai', 0, 17, '1999-11-10', NULL, 0, 1000000, 800000)"
            );

            statement.execute(
                "CREATE TABLE sync_state(source TEXT, dataset TEXT, symbol TEXT, last_date TEXT, row_count INTEGER, cursor TEXT, updated_at TEXT)"
            );
            statement.execute(
                "INSERT INTO sync_state(source, dataset, symbol, last_date, row_count, cursor, updated_at) VALUES " +
                    "('tushare_kline', 'daily', '600000.SH', '2026-03-12', 42, '{}', '2026-03-12 17:30:00')"
            );

            statement.execute(
                "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT, value_type TEXT, category TEXT)"
            );
        }
    }

    private static int queryInt(Statement statement, String sql) throws SQLException {
        try (ResultSet resultSet = statement.executeQuery(sql)) {
            resultSet.next();
            return resultSet.getInt(1);
        }
    }

    private static String queryString(Statement statement, String sql) throws SQLException {
        try (ResultSet resultSet = statement.executeQuery(sql)) {
            resultSet.next();
            return resultSet.getString(1);
        }
    }
}
