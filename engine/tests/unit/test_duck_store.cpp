#include <gtest/gtest.h>
#include "trade/storage/duck_store.h"
#include <filesystem>
#include <string>

using namespace trade;

TEST(DuckStoreTest, Available) {
    EXPECT_TRUE(DuckStore::available());
}

TEST(DuckStoreTest, BasicQuery) {
    DuckStore db;
    auto rows = db.query("SELECT 42 AS answer");
    ASSERT_EQ(rows.size(), 1u);
    ASSERT_EQ(rows[0].size(), 1u);
    EXPECT_EQ(rows[0][0], "42");
}

TEST(DuckStoreTest, ExecuteCreateAndInsert) {
    DuckStore db;
    EXPECT_TRUE(db.execute("CREATE TABLE t (x INTEGER)"));
    EXPECT_TRUE(db.execute("INSERT INTO t VALUES (1), (2), (3)"));
    auto rows = db.query("SELECT sum(x) FROM t");
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0][0], "6");
}

TEST(DuckStoreTest, CountRowsNonexistentGlobReturnsNegOne) {
    DuckStore db;
    // File doesn't exist -> DuckDB returns error -> count_rows returns -1
    int64_t count = db.count_rows("/tmp/nonexistent_trade_test_*.parquet");
    EXPECT_EQ(count, -1);
}
