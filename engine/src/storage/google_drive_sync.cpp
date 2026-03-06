#include "trade/storage/google_drive_sync.h"

#include <nlohmann/json.hpp>
#include <curl/curl.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/bio.h>
#include <spdlog/spdlog.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>

namespace trade {

// ============================================================================
// Impl struct - defined here so helpers in the anonymous namespace can use it
// ============================================================================
struct GoogleDriveSync::Impl {
    Config cfg;

    // Cached OAuth2 access token + expiry
    std::string access_token;
    std::chrono::system_clock::time_point token_expiry;
    std::mutex token_mutex;

    // Cached folder IDs: relative path -> Google Drive file ID
    std::map<std::string, std::string> folder_id_cache;
    std::mutex folder_cache_mutex;

    // Service account credentials (loaded once)
    std::string client_email;
    std::string private_key_pem;
    bool creds_loaded = false;

    explicit Impl(Config c) : cfg(std::move(c)) {}
};

// Type alias defined at namespace trade scope (after Impl definition) so that
// anonymous namespace helpers can name the type without going through the
// private nested class access path.
using DriveImpl = GoogleDriveSync::Impl;

// ============================================================================
// Anonymous helpers
// ============================================================================
namespace {

// ----- curl global init -----
void ensure_curl_ready() {
    static const int kInit = []() {
        curl_global_init(CURL_GLOBAL_DEFAULT);
        return 0;
    }();
    (void)kInit;
}

// ----- write callback -----
static size_t write_cb(char* ptr, size_t size, size_t nmemb, std::string* out) {
    out->append(ptr, size * nmemb);
    return size * nmemb;
}

// ----- base64url encoding (no padding, URL-safe alphabet) -----
static const char* B64URL =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

std::string base64url_encode(const unsigned char* data, size_t len) {
    std::string out;
    out.reserve(((len + 2) / 3) * 4);
    for (size_t i = 0; i < len; i += 3) {
        uint32_t val = static_cast<uint8_t>(data[i]) << 16U;
        if (i + 1 < len) val |= static_cast<uint8_t>(data[i + 1]) << 8U;
        if (i + 2 < len) val |= static_cast<uint8_t>(data[i + 2]);
        out += B64URL[(val >> 18U) & 0x3FU];
        out += B64URL[(val >> 12U) & 0x3FU];
        if (i + 1 < len) out += B64URL[(val >> 6U) & 0x3FU];
        if (i + 2 < len) out += B64URL[val & 0x3FU];
    }
    return out;
}

std::string base64url_encode(const std::string& s) {
    return base64url_encode(reinterpret_cast<const unsigned char*>(s.data()), s.size());
}

// ----- URL encoding for query parameters -----
std::string url_encode(const std::string& value) {
    ensure_curl_ready();
    CURL* curl = curl_easy_init();
    if (!curl) return value;
    char* encoded = curl_easy_escape(curl, value.c_str(), static_cast<int>(value.size()));
    std::string out = encoded ? encoded : value;
    if (encoded) curl_free(encoded);
    curl_easy_cleanup(curl);
    return out;
}

// ----- JWT creation -----
std::string create_jwt(const std::string& client_email,
                       const std::string& private_key_pem,
                       const std::string& scope) {
    // Header
    const std::string header_json = R"({"alg":"RS256","typ":"JWT"})";
    const std::string header = base64url_encode(header_json);

    // Payload
    auto now = std::chrono::system_clock::now();
    int64_t iat = std::chrono::duration_cast<std::chrono::seconds>(
                      now.time_since_epoch()).count();
    int64_t exp = iat + 3600;

    nlohmann::json payload_obj = {
        {"iss",   client_email},
        {"scope", scope},
        {"aud",   "https://oauth2.googleapis.com/token"},
        {"exp",   exp},
        {"iat",   iat},
    };
    const std::string payload = base64url_encode(payload_obj.dump());

    // Signing input
    const std::string signing_input = header + "." + payload;

    // RSA-SHA256 sign using OpenSSL
    BIO* bio = BIO_new_mem_buf(private_key_pem.c_str(), -1);
    if (!bio) {
        spdlog::error("GoogleDriveSync: BIO_new_mem_buf failed");
        return "";
    }
    EVP_PKEY* pkey = PEM_read_bio_PrivateKey(bio, nullptr, nullptr, nullptr);
    BIO_free(bio);
    if (!pkey) {
        spdlog::error("GoogleDriveSync: failed to load private key from PEM");
        return "";
    }

    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) {
        EVP_PKEY_free(pkey);
        spdlog::error("GoogleDriveSync: EVP_MD_CTX_new failed");
        return "";
    }

    if (EVP_DigestSignInit(ctx, nullptr, EVP_sha256(), nullptr, pkey) != 1 ||
        EVP_DigestSignUpdate(ctx, signing_input.c_str(), signing_input.size()) != 1) {
        EVP_MD_CTX_free(ctx);
        EVP_PKEY_free(pkey);
        spdlog::error("GoogleDriveSync: DigestSign init/update failed");
        return "";
    }

    size_t sig_len = 0;
    if (EVP_DigestSignFinal(ctx, nullptr, &sig_len) != 1) {
        EVP_MD_CTX_free(ctx);
        EVP_PKEY_free(pkey);
        spdlog::error("GoogleDriveSync: DigestSignFinal (size query) failed");
        return "";
    }
    std::vector<unsigned char> sig(sig_len);
    if (EVP_DigestSignFinal(ctx, sig.data(), &sig_len) != 1) {
        EVP_MD_CTX_free(ctx);
        EVP_PKEY_free(pkey);
        spdlog::error("GoogleDriveSync: DigestSignFinal failed");
        return "";
    }
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);

    const std::string signature = base64url_encode(sig.data(), sig_len);
    return signing_input + "." + signature;
}

// ----- HTTP response helper -----
struct HttpResp {
    long code = 0;
    std::string body;
};

// Generic HTTP request helper. method = "GET", "POST", "PATCH", "DELETE".
HttpResp http_request(const std::string& method,
                      const std::string& url,
                      const std::string& content_type,
                      const std::string& body,
                      const std::string& bearer_token,
                      int timeout_ms) {
    ensure_curl_ready();
    HttpResp resp;

    CURL* curl = curl_easy_init();
    if (!curl) {
        spdlog::error("GoogleDriveSync: curl_easy_init failed");
        return resp;
    }

    std::string response_body;
    struct curl_slist* headers = nullptr;

    if (!content_type.empty()) {
        headers = curl_slist_append(headers, ("Content-Type: " + content_type).c_str());
    }
    if (!bearer_token.empty()) {
        headers = curl_slist_append(headers, ("Authorization: Bearer " + bearer_token).c_str());
    }

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response_body);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, static_cast<long>(timeout_ms));
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);

    if (method == "POST") {
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    } else if (method == "GET") {
        curl_easy_setopt(curl, CURLOPT_HTTPGET, 1L);
    } else if (method == "DELETE") {
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "DELETE");
    } else if (method == "PATCH") {
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PATCH");
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    } else {
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, method.c_str());
        if (!body.empty()) {
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
            curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
        }
    }

    const CURLcode rc = curl_easy_perform(curl);
    if (rc != CURLE_OK) {
        spdlog::warn("GoogleDriveSync: curl error: {}", curl_easy_strerror(rc));
    } else {
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &resp.code);
    }
    resp.body = std::move(response_body);

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    return resp;
}

HttpResp http_get(const std::string& url,
                  const std::string& bearer_token,
                  int timeout_ms) {
    return http_request("GET", url, "", "", bearer_token, timeout_ms);
}

HttpResp http_delete(const std::string& url,
                     const std::string& bearer_token,
                     int timeout_ms) {
    return http_request("DELETE", url, "", "", bearer_token, timeout_ms);
}

// ----- OAuth2 token exchange -----
bool fetch_access_token(DriveImpl* impl) {
    const std::string jwt = create_jwt(impl->client_email, impl->private_key_pem,
                                       "https://www.googleapis.com/auth/drive");
    if (jwt.empty()) return false;

    const std::string body =
        "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=" + jwt;
    const auto resp = http_request("POST",
                                   "https://oauth2.googleapis.com/token",
                                   "application/x-www-form-urlencoded",
                                   body, "", impl->cfg.timeout_ms);
    if (resp.code != 200) {
        spdlog::error("GoogleDriveSync: token exchange failed ({}): {}", resp.code, resp.body);
        return false;
    }
    auto j = nlohmann::json::parse(resp.body, nullptr, false);
    if (j.is_discarded() || !j.contains("access_token")) {
        spdlog::error("GoogleDriveSync: token response missing access_token");
        return false;
    }
    impl->access_token = j["access_token"].get<std::string>();
    impl->token_expiry = std::chrono::system_clock::now() + std::chrono::seconds(3500);
    return true;
}

std::string get_token(DriveImpl* impl) {
    std::lock_guard<std::mutex> lk(impl->token_mutex);
    if (impl->access_token.empty() ||
        std::chrono::system_clock::now() >= impl->token_expiry) {
        if (!fetch_access_token(impl)) return "";
    }
    return impl->access_token;
}

// ----- Drive folder helpers -----

// Find a file/folder by name within a parent folder. Returns "" if not found.
std::string find_in_folder(const std::string& parent_id,
                           const std::string& name,
                           const std::string& token,
                           int timeout_ms) {
    std::string q = "name = '" + name + "' and '" + parent_id +
                    "' in parents and trashed=false";
    const std::string url = "https://www.googleapis.com/drive/v3/files"
                            "?q=" + url_encode(q) +
                            "&fields=files(id,name)&pageSize=1";
    const auto resp = http_get(url, token, timeout_ms);
    if (resp.code != 200) return "";
    auto j = nlohmann::json::parse(resp.body, nullptr, false);
    if (!j.is_discarded() && j.contains("files") && !j["files"].empty()) {
        return j["files"][0]["id"].get<std::string>();
    }
    return "";
}

// Create a folder inside parent_id. Returns new folder ID or "".
std::string create_folder(const std::string& parent_id,
                          const std::string& name,
                          const std::string& token,
                          int timeout_ms) {
    nlohmann::json body_obj = {
        {"name", name},
        {"mimeType", "application/vnd.google-apps.folder"},
        {"parents", nlohmann::json::array({parent_id})},
    };
    const auto resp = http_request("POST",
                                   "https://www.googleapis.com/drive/v3/files?fields=id",
                                   "application/json",
                                   body_obj.dump(),
                                   token, timeout_ms);
    if (resp.code != 200) {
        spdlog::warn("GoogleDriveSync: create_folder failed ({}) for '{}'", resp.code, name);
        return "";
    }
    auto j = nlohmann::json::parse(resp.body, nullptr, false);
    if (!j.is_discarded() && j.contains("id")) return j["id"].get<std::string>();
    return "";
}

// Resolve a directory path like "kline/2026-01" to its folder ID,
// creating intermediate folders as needed.
std::string resolve_dir(DriveImpl* impl,
                        const std::string& rel_dir,
                        const std::string& token) {
    if (rel_dir.empty() || rel_dir == ".") return impl->cfg.root_folder_id;

    // Check cache first
    {
        std::lock_guard<std::mutex> lk(impl->folder_cache_mutex);
        auto it = impl->folder_id_cache.find(rel_dir);
        if (it != impl->folder_id_cache.end()) return it->second;
    }

    // Split path into components
    std::vector<std::string> parts;
    std::stringstream ss(rel_dir);
    std::string part;
    while (std::getline(ss, part, '/')) {
        if (!part.empty()) parts.push_back(part);
    }

    std::string cur_id = impl->cfg.root_folder_id;
    std::string cur_path;
    for (const auto& p : parts) {
        if (!cur_path.empty()) cur_path += "/";
        cur_path += p;

        // Check cache for this intermediate path
        {
            std::lock_guard<std::mutex> lk(impl->folder_cache_mutex);
            auto it = impl->folder_id_cache.find(cur_path);
            if (it != impl->folder_id_cache.end()) {
                cur_id = it->second;
                continue;
            }
        }

        std::string next_id = find_in_folder(cur_id, p, token, impl->cfg.timeout_ms);
        if (next_id.empty()) {
            next_id = create_folder(cur_id, p, token, impl->cfg.timeout_ms);
        }
        if (next_id.empty()) {
            spdlog::error("GoogleDriveSync: failed to resolve folder '{}'", cur_path);
            return "";
        }
        cur_id = next_id;
        {
            std::lock_guard<std::mutex> lk(impl->folder_cache_mutex);
            impl->folder_id_cache[cur_path] = cur_id;
        }
    }
    return cur_id;
}

} // namespace

// ============================================================================
// Constructor / destructor
// ============================================================================
GoogleDriveSync::GoogleDriveSync(Config cfg) : impl_(std::make_unique<Impl>(std::move(cfg))) {
    if (!std::filesystem::exists(impl_->cfg.service_account_json_path)) {
        spdlog::warn("GoogleDriveSync: key file not found: {}",
                     impl_->cfg.service_account_json_path);
        return;
    }
    std::ifstream f(impl_->cfg.service_account_json_path);
    if (!f.is_open()) {
        spdlog::error("GoogleDriveSync: cannot open key file: {}",
                      impl_->cfg.service_account_json_path);
        return;
    }
    auto j = nlohmann::json::parse(f, nullptr, false);
    if (j.is_discarded()) {
        spdlog::error("GoogleDriveSync: failed to parse service account JSON");
        return;
    }
    impl_->client_email    = j.value("client_email", "");
    impl_->private_key_pem = j.value("private_key", "");
    if (impl_->client_email.empty() || impl_->private_key_pem.empty()) {
        spdlog::error("GoogleDriveSync: missing client_email or private_key in JSON");
        return;
    }
    impl_->creds_loaded = true;
    spdlog::info("GoogleDriveSync: loaded credentials for {}", impl_->client_email);
}

GoogleDriveSync::~GoogleDriveSync() = default;

// ============================================================================
// available()
// ============================================================================
bool GoogleDriveSync::available() const {
    return impl_->creds_loaded && !impl_->cfg.root_folder_id.empty();
}

// ============================================================================
// upload_bytes
// ============================================================================
bool GoogleDriveSync::upload_bytes(const std::string& remote_rel_path,
                                   const std::vector<uint8_t>& data) {
    if (!available()) {
        spdlog::warn("GoogleDriveSync: not available, skipping upload of {}", remote_rel_path);
        return false;
    }

    const auto slash = remote_rel_path.rfind('/');
    const std::string dir  = (slash == std::string::npos) ? ""
                                                          : remote_rel_path.substr(0, slash);
    const std::string name = (slash == std::string::npos) ? remote_rel_path
                                                          : remote_rel_path.substr(slash + 1);

    const std::string token = get_token(impl_.get());
    if (token.empty()) return false;

    const std::string parent_id = resolve_dir(impl_.get(), dir, token);
    if (parent_id.empty()) return false;

    // Check for existing file to decide create vs update
    const std::string existing_id = find_in_folder(parent_id, name, token,
                                                   impl_->cfg.timeout_ms);

    // Build multipart body
    const std::string boundary = "trade_upload_boundary_a1b2c3";
    const std::string meta_json = [&]() -> std::string {
        if (existing_id.empty()) {
            nlohmann::json m = {
                {"name", name},
                {"parents", nlohmann::json::array({parent_id})},
            };
            return m.dump();
        }
        nlohmann::json m = {{"name", name}};
        return m.dump();
    }();

    std::string body;
    body.reserve(data.size() + 512);
    body += "--" + boundary + "\r\n";
    body += "Content-Type: application/json; charset=UTF-8\r\n\r\n";
    body += meta_json + "\r\n";
    body += "--" + boundary + "\r\n";
    body += "Content-Type: application/octet-stream\r\n\r\n";
    body.append(reinterpret_cast<const char*>(data.data()), data.size());
    body += "\r\n--" + boundary + "--";

    std::string url;
    std::string method;
    if (existing_id.empty()) {
        url    = "https://www.googleapis.com/upload/drive/v3/files"
                 "?uploadType=multipart&fields=id";
        method = "POST";
    } else {
        url    = "https://www.googleapis.com/upload/drive/v3/files/" +
                 existing_id + "?uploadType=multipart";
        method = "PATCH";
    }

    const auto resp = http_request(method, url,
                                   "multipart/related; boundary=" + boundary,
                                   body, token, impl_->cfg.timeout_ms);
    if (resp.code != 200) {
        spdlog::error("GoogleDriveSync: upload failed ({}) for {}: {}",
                      resp.code, remote_rel_path, resp.body);
        return false;
    }
    spdlog::debug("GoogleDriveSync: uploaded {} bytes to {}", data.size(), remote_rel_path);
    return true;
}

// ============================================================================
// download_bytes
// ============================================================================
bool GoogleDriveSync::download_bytes(const std::string& remote_rel_path,
                                     std::vector<uint8_t>* out) {
    if (!out) return false;
    out->clear();

    if (!available()) {
        spdlog::warn("GoogleDriveSync: not available, skipping download of {}",
                     remote_rel_path);
        return false;
    }

    const auto slash = remote_rel_path.rfind('/');
    const std::string dir  = (slash == std::string::npos) ? ""
                                                          : remote_rel_path.substr(0, slash);
    const std::string name = (slash == std::string::npos) ? remote_rel_path
                                                          : remote_rel_path.substr(slash + 1);

    const std::string token = get_token(impl_.get());
    if (token.empty()) return false;

    const std::string parent_id = resolve_dir(impl_.get(), dir, token);
    if (parent_id.empty()) return false;

    const std::string file_id = find_in_folder(parent_id, name, token,
                                               impl_->cfg.timeout_ms);
    if (file_id.empty()) {
        spdlog::warn("GoogleDriveSync: file not found: {}", remote_rel_path);
        return false;
    }

    const std::string url = "https://www.googleapis.com/drive/v3/files/" +
                            file_id + "?alt=media";
    const auto resp = http_get(url, token, impl_->cfg.timeout_ms);
    if (resp.code != 200) {
        spdlog::error("GoogleDriveSync: download failed ({}) for {}",
                      resp.code, remote_rel_path);
        return false;
    }
    out->assign(resp.body.begin(), resp.body.end());
    spdlog::debug("GoogleDriveSync: downloaded {} bytes from {}", out->size(), remote_rel_path);
    return true;
}

// ============================================================================
// delete_path
// ============================================================================
bool GoogleDriveSync::delete_path(const std::string& remote_rel_path) {
    if (!available()) {
        spdlog::warn("GoogleDriveSync: not available, skipping delete of {}",
                     remote_rel_path);
        return false;
    }

    const auto slash = remote_rel_path.rfind('/');
    const std::string dir  = (slash == std::string::npos) ? ""
                                                          : remote_rel_path.substr(0, slash);
    const std::string name = (slash == std::string::npos) ? remote_rel_path
                                                          : remote_rel_path.substr(slash + 1);

    const std::string token = get_token(impl_.get());
    if (token.empty()) return false;

    const std::string parent_id = resolve_dir(impl_.get(), dir, token);
    if (parent_id.empty()) return false;

    const std::string file_id = find_in_folder(parent_id, name, token,
                                               impl_->cfg.timeout_ms);
    if (file_id.empty()) {
        // Not found counts as success for idempotent delete
        spdlog::debug("GoogleDriveSync: delete_path: file not found (ok): {}",
                      remote_rel_path);
        return true;
    }

    const std::string url = "https://www.googleapis.com/drive/v3/files/" + file_id;
    const auto resp = http_delete(url, token, impl_->cfg.timeout_ms);
    // Drive returns 204 No Content on success
    if (resp.code != 204 && resp.code != 200) {
        spdlog::error("GoogleDriveSync: delete failed ({}) for {}",
                      resp.code, remote_rel_path);
        return false;
    }

    // Invalidate the folder cache entry for the containing directory
    {
        std::lock_guard<std::mutex> lk(impl_->folder_cache_mutex);
        impl_->folder_id_cache.erase(dir);
    }

    spdlog::debug("GoogleDriveSync: deleted {}", remote_rel_path);
    return true;
}

// ============================================================================
// list_files
// ============================================================================
bool GoogleDriveSync::list_files(const std::string& remote_rel_dir,
                                 std::vector<std::string>* names_out) {
    if (!names_out) return false;
    names_out->clear();

    if (!available()) {
        spdlog::warn("GoogleDriveSync: not available, skipping list_files of {}",
                     remote_rel_dir);
        return false;
    }

    const std::string token = get_token(impl_.get());
    if (token.empty()) return false;

    const std::string dir_id = resolve_dir(impl_.get(), remote_rel_dir, token);
    if (dir_id.empty()) return false;

    // Paginate through results
    std::string page_token;
    do {
        const std::string q = "'" + dir_id + "' in parents and trashed=false";
        std::string url = "https://www.googleapis.com/drive/v3/files"
                          "?q=" + url_encode(q) +
                          "&fields=nextPageToken,files(name)&pageSize=1000";
        if (!page_token.empty()) {
            url += "&pageToken=" + url_encode(page_token);
        }
        const auto resp = http_get(url, token, impl_->cfg.timeout_ms);
        if (resp.code != 200) {
            spdlog::error("GoogleDriveSync: list_files failed ({}) for {}",
                          resp.code, remote_rel_dir);
            return false;
        }
        auto j = nlohmann::json::parse(resp.body, nullptr, false);
        if (j.is_discarded()) {
            spdlog::error("GoogleDriveSync: list_files JSON parse error");
            return false;
        }
        if (j.contains("files")) {
            for (const auto& f : j["files"]) {
                if (f.contains("name")) {
                    names_out->push_back(f["name"].get<std::string>());
                }
            }
        }
        page_token = j.value("nextPageToken", "");
    } while (!page_token.empty());

    return true;
}

} // namespace trade
