#pragma once

#include "trade/common/types.h"
#include <string>
#include <vector>

namespace trade {

// Parse "YYYY-MM-DD" to Date
Date parse_date(const std::string& s);

// Format Date to "YYYY-MM-DD"
std::string format_date(Date d);

// Parse "YYYY-MM-DD HH:MM:SS" to Timestamp
Timestamp parse_timestamp(const std::string& s);

// Format Timestamp to string
std::string format_timestamp(Timestamp ts);

// Get year from Date
int date_year(Date d);

// Get month from Date (1-12)
int date_month(Date d);

// Get day from Date (1-31)
int date_day(Date d);

// Day of week (0=Sunday, 1=Monday, ..., 6=Saturday)
int day_of_week(Date d);

// Is the date a Chinese trading day? (excludes weekends + holidays)
// Note: requires loading a holiday calendar
bool is_trading_day(Date d);

// Get the next trading day after d
Date next_trading_day(Date d);

// Get the previous trading day before d
Date prev_trading_day(Date d);

// Get N trading days before/after d (positive = forward, negative = backward)
Date offset_trading_days(Date d, int n);

// Get all trading days in [start, end]
std::vector<Date> trading_days_between(Date start, Date end);

// Load holiday calendar from file (call once at startup)
void load_holiday_calendar(const std::string& path);

// Check if date is in spring festival window (pre_3d / post_5d)
bool is_spring_festival_window(Date d);

// Check if date is in national day window
bool is_national_day_window(Date d);

// Check if date is in two-sessions window
bool is_two_sessions_window(Date d);

// Check if date is month-end (last 3 trading days)
bool is_month_end(Date d);

} // namespace trade
