package io.tradedb.jdbc;

import org.sqlite.JDBC;

import java.sql.Connection;
import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.DriverPropertyInfo;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.Properties;
import java.util.logging.Logger;

public final class TradeDbDriver implements Driver {
    private static final Logger LOGGER = Logger.getLogger(TradeDbDriver.class.getName());
    private static final String SQLITE_PREFIX = "jdbc:sqlite:";

    static {
        try {
            DriverManager.registerDriver(new TradeDbDriver());
        } catch (SQLException exc) {
            throw new ExceptionInInitializerError(exc);
        }
    }

    @Override
    public Connection connect(String url, Properties info) throws SQLException {
        if (!acceptsURL(url)) {
            return null;
        }

        TradeDbJdbcUrl options = TradeDbJdbcUrl.parse(url, info);
        Connection connection = new JDBC().connect(SQLITE_PREFIX + options.databasePath(), new Properties());
        if (connection == null) {
            throw new SQLException("sqlite-jdbc did not return a connection for " + options.databasePath());
        }

        try {
            TradeDbBootstrap.initialize(connection, options);
        } catch (SQLException exc) {
            try {
                connection.close();
            } catch (SQLException closeExc) {
                exc.addSuppressed(closeExc);
            }
            throw exc;
        }

        return connection;
    }

    @Override
    public boolean acceptsURL(String url) {
        return url != null && url.startsWith(TradeDbJdbcUrl.URL_PREFIX);
    }

    @Override
    public DriverPropertyInfo[] getPropertyInfo(String url, Properties info) {
        DriverPropertyInfo dataRoot = property("dataRoot", null, "Trade data root directory. Resolves to .db/trade.db or .metadata/trade.db.");
        DriverPropertyInfo dbPath = property("dbPath", null, "Explicit path to a trade.db SQLite file.");
        DriverPropertyInfo readOnly = property("readOnly", "false", "Enable PRAGMA query_only after compatibility bootstrap.");
        DriverPropertyInfo busyTimeout = property("busyTimeoutMs", "30000", "SQLite busy timeout in milliseconds.");
        DriverPropertyInfo bootstrapCompat = property("bootstrapCompat", "true", "Create temporary compatibility views for legacy table names.");
        return new DriverPropertyInfo[]{dataRoot, dbPath, readOnly, busyTimeout, bootstrapCompat};
    }

    @Override
    public int getMajorVersion() {
        return 0;
    }

    @Override
    public int getMinorVersion() {
        return 1;
    }

    @Override
    public boolean jdbcCompliant() {
        return false;
    }

    @Override
    public Logger getParentLogger() throws SQLFeatureNotSupportedException {
        return LOGGER;
    }

    private static DriverPropertyInfo property(String name, String value, String description) {
        DriverPropertyInfo info = new DriverPropertyInfo(name, value);
        info.description = description;
        return info;
    }
}
