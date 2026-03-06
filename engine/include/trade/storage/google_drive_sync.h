#pragma once
#include "trade/storage/cloud_sync.h"
#include <memory>
#include <string>

namespace trade {

// Google Drive cloud sync using Service Account authentication.
//
// Authentication: loads a service account JSON key file, creates
// a signed JWT (RSA-SHA256 via OpenSSL), exchanges it for an OAuth2
// access token, then uses that token for Drive API v3 calls.
//
// The service account must have the Drive API enabled and access
// to the root_folder_id.
//
// Service account JSON format (from Google Cloud Console):
//   {
//     "type": "service_account",
//     "project_id": "...",
//     "private_key_id": "...",
//     "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n",
//     "client_email": "...@...iam.gserviceaccount.com",
//     ...
//   }
class GoogleDriveSync final : public CloudSync {
public:
    struct Config {
        std::string service_account_json_path;  // path to JSON key file
        std::string root_folder_id;             // Google Drive folder ID (root for all ops)
        int timeout_ms  = 30'000;
        int retry_count = 2;
    };

    explicit GoogleDriveSync(Config cfg);
    ~GoogleDriveSync();

    GoogleDriveSync(const GoogleDriveSync&) = delete;
    GoogleDriveSync& operator=(const GoogleDriveSync&) = delete;

    bool upload_bytes(const std::string& remote_rel_path,
                      const std::vector<uint8_t>& data) override;

    bool download_bytes(const std::string& remote_rel_path,
                        std::vector<uint8_t>* out) override;

    bool delete_path(const std::string& remote_rel_path) override;

    bool list_files(const std::string& remote_rel_dir,
                    std::vector<std::string>* names_out) override;

    bool available() const override;

    // Impl is defined in the .cpp file (pimpl idiom).
    struct Impl;

private:
    std::unique_ptr<Impl> impl_;
};

} // namespace trade
