#include "trade/sentiment/xueqiu_source.h"
#include "trade/sentiment/text_cleaner.h"

#include <curl/curl.h>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <chrono>
#include <sstream>
#include <thread>

namespace trade {

// ---------------------------------------------------------------------------
// libcurl write callback
// ---------------------------------------------------------------------------
static size_t xueqiu_write_cb(char* ptr, size_t size, size_t nmemb, void* ud) {
    auto* buf = static_cast<std::string*>(ud);
    size_t total = size * nmemb;
    buf->append(ptr, total);
    return total;
}

// ---------------------------------------------------------------------------
// Construction / destruction
// ---------------------------------------------------------------------------
XueqiuSource::XueqiuSource() : config_{} {}
XueqiuSource::XueqiuSource(Config cfg) : config_(std::move(cfg)) {}

XueqiuSource::~XueqiuSource() = default;

// ---------------------------------------------------------------------------
// ITextSource
// ---------------------------------------------------------------------------
std::vector<TextEvent> XueqiuSource::fetch(Date date) {
    std::vector<TextEvent> all;
    for (int page = 1; page <= config_.max_pages; ++page) {
        auto page_events = fetch_page(page);
        for (auto& ev : page_events) {
            auto ev_date = std::chrono::floor<std::chrono::days>(ev.timestamp);
            if (ev_date == date) {
                all.push_back(std::move(ev));
            }
        }
        // Xueqiu returns newest first; stop if we passed the target date
        if (!page_events.empty()) {
            auto oldest = std::chrono::floor<std::chrono::days>(
                page_events.back().timestamp);
            if (oldest < date) break;
        }
    }
    return all;
}

std::vector<TextEvent> XueqiuSource::fetch_range(Date start, Date end) {
    std::vector<TextEvent> all;
    for (int page = 1; page <= config_.max_pages; ++page) {
        auto page_events = fetch_page(page);
        for (auto& ev : page_events) {
            auto ev_date = std::chrono::floor<std::chrono::days>(ev.timestamp);
            if (ev_date >= start && ev_date <= end) {
                all.push_back(std::move(ev));
            }
        }
        if (!page_events.empty()) {
            auto oldest = std::chrono::floor<std::chrono::days>(
                page_events.back().timestamp);
            if (oldest < start) break;
        }
    }
    return all;
}

bool XueqiuSource::is_available() const {
    return !config_.cookie.empty();
}

// ---------------------------------------------------------------------------
// Cookie management
// ---------------------------------------------------------------------------
bool XueqiuSource::refresh_cookie() {
    // Visit the Xueqiu homepage to obtain a fresh session cookie.
    CURL* curl = curl_easy_init();
    if (!curl) return false;

    std::string body;
    std::string header_buf;

    auto header_cb = [](char* ptr, size_t size, size_t nmemb, void* ud) -> size_t {
        auto* hdr = static_cast<std::string*>(ud);
        hdr->append(ptr, size * nmemb);
        return size * nmemb;
    };

    curl_easy_setopt(curl, CURLOPT_URL, "https://xueqiu.com/");
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, xueqiu_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
    curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION,
                     static_cast<size_t(*)(char*, size_t, size_t, void*)>(header_cb));
    curl_easy_setopt(curl, CURLOPT_HEADERDATA, &header_buf);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, static_cast<long>(config_.timeout_ms));
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, config_.user_agent.c_str());
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        spdlog::warn("[XueqiuSource] refresh_cookie failed: curl={}",
                     static_cast<int>(res));
        return false;
    }

    // Extract Set-Cookie headers (look for xq_a_token or u)
    std::string cookie;
    std::istringstream iss(header_buf);
    std::string line;
    while (std::getline(iss, line)) {
        if (line.find("Set-Cookie:") != std::string::npos ||
            line.find("set-cookie:") != std::string::npos) {
            auto colon = line.find(':');
            if (colon != std::string::npos) {
                auto val = line.substr(colon + 2);
                auto semi = val.find(';');
                if (semi != std::string::npos) val = val.substr(0, semi);
                if (!cookie.empty()) cookie += "; ";
                cookie += val;
            }
        }
    }

    if (!cookie.empty()) {
        config_.cookie = cookie;
        spdlog::info("[XueqiuSource] cookie refreshed ({} chars)", cookie.size());
        return true;
    }
    spdlog::warn("[XueqiuSource] no Set-Cookie in homepage response");
    return false;
}

void XueqiuSource::set_cookie(const std::string& cookie) {
    config_.cookie = cookie;
}

// ---------------------------------------------------------------------------
// Fetch a single page from Xueqiu hot timeline
// ---------------------------------------------------------------------------
std::vector<TextEvent> XueqiuSource::fetch_page(int page) {
    // Rate limit
    std::this_thread::sleep_for(std::chrono::milliseconds(config_.rate_limit_ms));

    // Xueqiu v4 statuses API: hot posts / home timeline
    std::string url = "https://xueqiu.com/statuses/hot/listV2.json"
                      "?since_id=-1&max_id=-1&size=20&page=" +
                      std::to_string(page);

    std::string json_str = http_get(url);
    if (json_str.empty()) return {};

    return parse_response(json_str);
}

// ---------------------------------------------------------------------------
// Parse JSON response
// ---------------------------------------------------------------------------
std::vector<TextEvent> XueqiuSource::parse_response(const std::string& json_str) {
    std::vector<TextEvent> events;

    try {
        auto root = nlohmann::json::parse(json_str);

        // Xueqiu returns { "list": [ { ... }, ... ] } or similar
        nlohmann::json items;
        if (root.contains("list") && root["list"].is_array()) {
            items = root["list"];
        } else if (root.contains("data") && root["data"].is_array()) {
            items = root["data"];
        } else if (root.contains("data") && root["data"].contains("list")) {
            items = root["data"]["list"];
        } else {
            spdlog::debug("[XueqiuSource] unexpected JSON structure");
            return {};
        }

        for (const auto& item : items) {
            TextEvent ev;
            ev.source = "xueqiu";

            // Extract text from the post
            if (item.contains("text") && item["text"].is_string()) {
                ev.raw_text = item["text"].get<std::string>();
            } else if (item.contains("description") && item["description"].is_string()) {
                ev.raw_text = item["description"].get<std::string>();
            }

            if (item.contains("title") && item["title"].is_string()) {
                ev.title = item["title"].get<std::string>();
            }

            // URL
            if (item.contains("target") && item["target"].is_string()) {
                ev.url = "https://xueqiu.com" + item["target"].get<std::string>();
            }

            // Timestamp (Xueqiu uses milliseconds since epoch)
            if (item.contains("created_at") && item["created_at"].is_number()) {
                auto ms = item["created_at"].get<int64_t>();
                ev.timestamp = Timestamp(std::chrono::milliseconds(ms));
            } else {
                ev.timestamp = std::chrono::system_clock::now();
            }

            // Clean HTML tags from text
            ev.title = TextCleaner::remove_html_tags(ev.title);
            ev.raw_text = TextCleaner::remove_html_tags(ev.raw_text);
            ev.content_hash = TextCleaner::content_hash(ev.title + ev.raw_text);

            if (!ev.raw_text.empty()) {
                events.push_back(std::move(ev));
            }
        }
    } catch (const nlohmann::json::exception& e) {
        spdlog::warn("[XueqiuSource] JSON parse error: {}", e.what());
    }

    return events;
}

// ---------------------------------------------------------------------------
// HTTP GET with cookie, retry, and 40x detection
// ---------------------------------------------------------------------------
std::string XueqiuSource::http_get(const std::string& url) {
    for (int attempt = 0; attempt <= config_.retry_count; ++attempt) {
        if (attempt > 0) {
            std::this_thread::sleep_for(
                std::chrono::milliseconds(config_.rate_limit_ms * attempt));
        }

        std::string response;
        CURL* curl = curl_easy_init();
        if (!curl) continue;

        struct curl_slist* headers = nullptr;
        std::string cookie_header = "Cookie: " + config_.cookie;
        headers = curl_slist_append(headers, cookie_header.c_str());
        headers = curl_slist_append(headers, "Accept: application/json");

        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, xueqiu_write_cb);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS,
                         static_cast<long>(config_.timeout_ms));
        curl_easy_setopt(curl, CURLOPT_USERAGENT, config_.user_agent.c_str());
        curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
        curl_easy_setopt(curl, CURLOPT_ACCEPT_ENCODING, "");
        curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

        CURLcode res = curl_easy_perform(curl);
        long http_code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
        curl_easy_cleanup(curl);
        curl_slist_free_all(headers);

        if (res == CURLE_OK && http_code >= 200 && http_code < 300) {
            return response;
        }

        // Cookie expired -> try to refresh
        if (http_code == 400 || http_code == 403) {
            spdlog::info("[XueqiuSource] HTTP {} - attempting cookie refresh", http_code);
            if (refresh_cookie()) continue;
        }

        spdlog::warn("[XueqiuSource] HTTP GET {} failed: curl={} http={}",
                     url, static_cast<int>(res), http_code);
    }

    return "";
}

} // namespace trade
