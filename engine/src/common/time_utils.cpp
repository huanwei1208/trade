#include "trade/common/time_utils.h"
#include <chrono>
#include <format>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <set>
#include <algorithm>

namespace trade {

namespace {
    // Global holiday set, loaded once at startup
    std::set<Date> g_holidays;
    bool g_calendar_loaded = false;

    // Chinese calendar events (approximate dates, should be loaded from config)
    // Spring Festival dates vary by year - these are placeholders
    struct CalendarEvents {
        std::vector<std::pair<Date, Date>> spring_festival_windows;  // (pre_3d, post_5d)
        std::vector<std::pair<Date, Date>> national_day_windows;
        std::vector<std::pair<Date, Date>> two_sessions_windows;
    };
    CalendarEvents g_events;
}

Date parse_date(const std::string& s) {
    int y, m, d;
    char sep1, sep2;
    std::istringstream iss(s);
    iss >> y >> sep1 >> m >> sep2 >> d;
    return std::chrono::sys_days{
        std::chrono::year{y} / std::chrono::month{static_cast<unsigned>(m)} /
        std::chrono::day{static_cast<unsigned>(d)}
    };
}

std::string format_date(Date d) {
    auto ymd = std::chrono::year_month_day{d};
    char buf[11];
    std::snprintf(buf, sizeof(buf), "%04d-%02d-%02d",
                  static_cast<int>(ymd.year()),
                  static_cast<unsigned>(ymd.month()),
                  static_cast<unsigned>(ymd.day()));
    return std::string(buf);
}

Timestamp parse_timestamp(const std::string& s) {
    std::tm tm = {};
    std::istringstream iss(s);
    iss >> std::get_time(&tm, "%Y-%m-%d %H:%M:%S");
    auto tp = std::chrono::system_clock::from_time_t(std::mktime(&tm));
    return tp;
}

std::string format_timestamp(Timestamp ts) {
    auto time_t = std::chrono::system_clock::to_time_t(ts);
    std::tm tm = *std::localtime(&time_t);
    char buf[20];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
    return std::string(buf);
}

int date_year(Date d) {
    return static_cast<int>(std::chrono::year_month_day{d}.year());
}

int date_month(Date d) {
    return static_cast<unsigned>(std::chrono::year_month_day{d}.month());
}

int date_day(Date d) {
    return static_cast<unsigned>(std::chrono::year_month_day{d}.day());
}

int day_of_week(Date d) {
    auto wd = std::chrono::weekday{d};
    return wd.c_encoding(); // 0=Sun, 1=Mon, ..., 6=Sat
}

bool is_trading_day(Date d) {
    auto wd = day_of_week(d);
    if (wd == 0 || wd == 6) return false; // weekend
    if (g_calendar_loaded && g_holidays.count(d)) return false;
    return true;
}

Date next_trading_day(Date d) {
    d += std::chrono::days{1};
    while (!is_trading_day(d)) {
        d += std::chrono::days{1};
    }
    return d;
}

Date prev_trading_day(Date d) {
    d -= std::chrono::days{1};
    while (!is_trading_day(d)) {
        d -= std::chrono::days{1};
    }
    return d;
}

Date offset_trading_days(Date d, int n) {
    if (n > 0) {
        for (int i = 0; i < n; ++i) d = next_trading_day(d);
    } else if (n < 0) {
        for (int i = 0; i < -n; ++i) d = prev_trading_day(d);
    }
    return d;
}

std::vector<Date> trading_days_between(Date start, Date end) {
    std::vector<Date> days;
    for (auto d = start; d <= end; d += std::chrono::days{1}) {
        if (is_trading_day(d)) {
            days.push_back(d);
        }
    }
    return days;
}

void load_holiday_calendar(const std::string& path) {
    g_holidays.clear();

    std::ifstream file(path);
    if (!file.is_open()) {
        // If the file cannot be opened, mark as loaded with an empty set so
        // that is_trading_day still filters weekends correctly.
        g_calendar_loaded = true;
        return;
    }

    std::string line;
    while (std::getline(file, line)) {
        // Trim leading/trailing whitespace
        auto start = line.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) continue;
        auto end = line.find_last_not_of(" \t\r\n");
        line = line.substr(start, end - start + 1);

        // Skip empty lines and comment lines (starting with '#')
        if (line.empty() || line[0] == '#') continue;

        // Parse YYYY-MM-DD
        if (line.size() >= 10) {
            int y = 0, m = 0, d = 0;
            char sep1 = 0, sep2 = 0;
            std::istringstream iss(line);
            iss >> y >> sep1 >> m >> sep2 >> d;
            if (y > 0 && m >= 1 && m <= 12 && d >= 1 && d <= 31
                && sep1 == '-' && sep2 == '-') {
                Date date = std::chrono::sys_days{
                    std::chrono::year{y} /
                    std::chrono::month{static_cast<unsigned>(m)} /
                    std::chrono::day{static_cast<unsigned>(d)}
                };
                g_holidays.insert(date);
            }
        }
    }

    g_calendar_loaded = true;
}

bool is_spring_festival_window(Date d) {
    for (const auto& [start, end] : g_events.spring_festival_windows) {
        if (d >= start && d <= end) return true;
    }
    return false;
}

bool is_national_day_window(Date d) {
    for (const auto& [start, end] : g_events.national_day_windows) {
        if (d >= start && d <= end) return true;
    }
    return false;
}

bool is_two_sessions_window(Date d) {
    for (const auto& [start, end] : g_events.two_sessions_windows) {
        if (d >= start && d <= end) return true;
    }
    return false;
}

bool is_month_end(Date d) {
    auto ymd = std::chrono::year_month_day{d};
    auto last = std::chrono::year_month_day_last{ymd.year(), std::chrono::month_day_last{ymd.month()}};
    auto last_date = std::chrono::sys_days{last};
    // Within last 3 trading days of month
    int trading_days_remaining = 0;
    for (auto dt = d; dt <= last_date; dt += std::chrono::days{1}) {
        if (is_trading_day(dt)) trading_days_remaining++;
    }
    return trading_days_remaining <= 3;
}

} // namespace trade
