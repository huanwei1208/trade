#pragma once

#include "trade/cli/args.h"
#include "trade/common/config.h"
#include "trade/common/types.h"
#include "trade/model/bar.h"
#include "trade/storage/metadata_store.h"
#include <optional>
#include <string>
#include <vector>

namespace trade::cli {

struct SqlViewDef {
    std::string dataset_id;
    std::string view_name;
    std::string glob_path;
};

struct MetadataHealth {
    bool ok = false;
    size_t instrument_count = 0;
};

std::pair<Date, Date> resolve_dates(const CliArgs& args,
                                    const std::string& default_start);
std::vector<Bar> load_bars(const std::string& symbol,
                           const Config& config);

std::string sql_escape(const std::string& s);
std::vector<SqlViewDef> discover_sql_views(const Config& config);
std::string build_sql_init(const std::vector<SqlViewDef>& views);
std::string build_metadata_views_sql(const Config& config);

MetadataHealth assess_metadata_health(MetadataStore& metadata);

} // namespace trade::cli
