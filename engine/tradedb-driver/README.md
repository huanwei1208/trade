# tradedb-driver

`tradedb-driver` 提供一个 `jdbc:tradedb:` JDBC URL，底层连接到仓库里的 TradeDB SQLite 文件。

默认解析规则：

- `dataRoot/.db/trade.db`
- 如果不存在，则回退到 `dataRoot/.metadata/trade.db`

支持的 URL 形式：

```text
jdbc:tradedb:
jdbc:tradedb:data
jdbc:tradedb:/abs/path/to/data
jdbc:tradedb:/abs/path/to/trade.db
jdbc:tradedb:data?readOnly=true&busyTimeoutMs=5000
```

也支持通过 `Properties` 传参：

- `dataRoot`
- `dbPath`
- `readOnly`
- `busyTimeoutMs`
- `bootstrapCompat`

连接建立后会创建一组临时兼容视图：

- `signal_cache -> signals`
- `bus_events -> event_log`
- `events -> market_events`
- `instrument_sector_members -> sector_members`
- `downloads -> sync_state`
- `watermarks -> sync_state`
- `meta_instruments -> instruments + sector_members`

## SDKMAN

项目目录下带了 `.sdkmanrc`，按当前工作区环境固定到：

```text
java=8.0.265-local
maven=3.9.12
```

使用方式：

```bash
source "$HOME/.sdkman/bin/sdkman-init.sh"
cd engine/tradedb-driver
sdk env
mvn test
```

## Java 示例

```java
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

public class Example {
    public static void main(String[] args) throws Exception {
        Class.forName("io.tradedb.jdbc.TradeDbDriver");

        try (Connection conn = DriverManager.getConnection("jdbc:tradedb:data?readOnly=true");
             Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM signals")) {
            rs.next();
            System.out.println(rs.getInt(1));
        }
    }
}
```
