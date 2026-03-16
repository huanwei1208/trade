package io.tradedb.jdbc;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

final class TradeDbBootstrap {
    private TradeDbBootstrap() {
    }

    static void initialize(Connection connection, TradeDbJdbcUrl options) throws SQLException {
        configureSession(connection, options);

        if (options.bootstrapCompat()) {
            createCompatibilityViews(connection);
        }

        if (options.readOnly()) {
            executePragma(connection, "PRAGMA query_only = ON");
        }
    }

    private static void configureSession(Connection connection, TradeDbJdbcUrl options) throws SQLException {
        executePragma(connection, "PRAGMA foreign_keys = ON");
        executePragma(connection, "PRAGMA temp_store = MEMORY");
        executePragma(connection, "PRAGMA busy_timeout = " + options.busyTimeoutMs());

        if (!options.readOnly()) {
            executePragma(connection, "PRAGMA journal_mode = WAL");
            executePragma(connection, "PRAGMA synchronous = NORMAL");
        }
    }

    private static void createCompatibilityViews(Connection connection) throws SQLException {
        if (exists(connection, "signals")) {
            createTempView(connection, "signal_cache", "SELECT * FROM signals");
        }
        if (exists(connection, "event_log")) {
            createTempView(connection, "bus_events", "SELECT * FROM event_log");
        }
        if (exists(connection, "market_events")) {
            createTempView(connection, "events", "SELECT * FROM market_events");
        }
        if (exists(connection, "sector_members")) {
            createTempView(
                connection,
                "instrument_sector_members",
                "SELECT symbol, sector_code, sector_name, industry_code, updated_at FROM sector_members"
            );
        }
        if (exists(connection, "sync_state")) {
            createTempView(
                connection,
                "downloads",
                "SELECT symbol, NULL AS start_date, last_date AS end_date, row_count, updated_at AS downloaded_at " +
                    "FROM sync_state WHERE source = 'tushare_kline' AND dataset = 'daily'"
            );
            createTempView(
                connection,
                "watermarks",
                "SELECT source, dataset, symbol, last_date AS last_event_date, cursor AS cursor_payload, updated_at " +
                    "FROM sync_state"
            );
        }
        if (exists(connection, "instruments")) {
            if (exists(connection, "sector_members")) {
                createTempView(
                    connection,
                    "meta_instruments",
                    "SELECT i.symbol, i.name, i.market, i.market_name, i.board, " +
                        "COALESCE(m.industry_code, i.industry) AS industry, " +
                        "i.list_date, i.delist_date, i.status, i.total_shares, i.float_shares " +
                        "FROM instruments i LEFT JOIN sector_members m ON i.symbol = m.symbol"
                );
            } else {
                createTempView(
                    connection,
                    "meta_instruments",
                    "SELECT symbol, name, market, market_name, board, industry, list_date, delist_date, status, total_shares, float_shares " +
                        "FROM instruments"
                );
            }
        }
    }

    private static boolean exists(Connection connection, String objectName) throws SQLException {
        final String sql =
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? " +
                "UNION ALL " +
                "SELECT 1 FROM sqlite_temp_master WHERE type IN ('table', 'view') AND name = ? " +
                "LIMIT 1";
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, objectName);
            statement.setString(2, objectName);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next();
            }
        }
    }

    private static void createTempView(Connection connection,
                                       String viewName,
                                       String selectSql) throws SQLException {
        if (exists(connection, viewName)) {
            return;
        }
        String sql = "CREATE TEMP VIEW " + quoteIdentifier(viewName) + " AS " + selectSql;
        try (Statement statement = connection.createStatement()) {
            statement.execute(sql);
        }
    }

    private static void executePragma(Connection connection, String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.execute(sql);
        }
    }

    private static String quoteIdentifier(String identifier) {
        return "\"" + identifier.replace("\"", "\"\"") + "\"";
    }
}
