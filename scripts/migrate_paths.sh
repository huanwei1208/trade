#!/usr/bin/env bash
# One-time data directory migration script.
# Run once after deploying the new code, then verify and delete this file.
#
# Usage: bash scripts/migrate_paths.sh [data_root]
#   data_root defaults to "data" relative to current directory.

set -e

DATA="${1:-data}"
if [ ! -d "$DATA" ]; then
    echo "ERROR: data root '$DATA' not found. Pass the correct path as argument."
    exit 1
fi

cd "$DATA"
echo "Migrating data directory: $(pwd)"

# Create target directories
mkdir -p market .db

# Move market data directories
for d in kline fund_flow fundamental cross_asset northbound index macro; do
    if [ -d "$d" ]; then
        echo "  mv $d -> market/$d"
        mv "$d" market/
    fi
done

# Copy SQLite and DuckDB files to .db/
if [ -f ".metadata/trade.db" ]; then
    echo "  cp .metadata/trade.db -> .db/trade.db"
    cp .metadata/trade.db .db/trade.db
fi
if [ -f ".pipeline/state.duckdb" ]; then
    echo "  cp .pipeline/state.duckdb -> .db/pipeline.duckdb"
    cp .pipeline/state.duckdb .db/pipeline.duckdb
fi
if [ -f ".meta/meta.duckdb" ]; then
    echo "  cp .meta/meta.duckdb -> .db/feed.duckdb"
    cp .meta/meta.duckdb .db/feed.duckdb
fi

echo ""
echo "Migration complete. Verify contents of .db/ and market/, then run:"
echo "  rm -rf .metadata .pipeline .meta raw"
echo ""
echo "After verification, delete this script: rm scripts/migrate_paths.sh"
