#include "trade/storage/cloud_sync.h"
#include "trade/storage/google_drive_sync.h"
#include <gtest/gtest.h>
#include <fstream>
#include <string>
#include <vector>

namespace {

// Test 1: NullCloudSync always returns false and reports unavailable.
TEST(CloudSync, NullSyncNotAvailable) {
    trade::NullCloudSync sync;
    EXPECT_FALSE(sync.available());
    EXPECT_FALSE(sync.upload_bytes("foo.parquet", {}));
    std::vector<uint8_t> out;
    EXPECT_FALSE(sync.download_bytes("foo.parquet", &out));
    EXPECT_FALSE(sync.delete_path("foo.parquet"));
    std::vector<std::string> names;
    EXPECT_FALSE(sync.list_files("dir", &names));
}

// Test 2: NullCloudSync delete_paths (default impl) also returns false.
TEST(CloudSync, NullSyncDeletePathsFalse) {
    trade::NullCloudSync sync;
    EXPECT_FALSE(sync.delete_paths({"a.parquet", "b.parquet"}));
}

// Test 3: GoogleDriveSync with non-existent key file is not available.
TEST(GoogleDriveSync, UnavailableWithMissingKeyFile) {
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = "/tmp/nonexistent_gd_key_xyz.json";
    cfg.root_folder_id = "test_folder_id";
    trade::GoogleDriveSync sync(cfg);
    EXPECT_FALSE(sync.available());
}

// Test 4: GoogleDriveSync with malformed JSON key file is not available.
TEST(GoogleDriveSync, UnavailableWithBadJson) {
    const std::string tmp = "/tmp/test_gd_key_bad_json.json";
    {
        std::ofstream f(tmp);
        f << "not valid json at all {{{";
    }
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = tmp;
    cfg.root_folder_id = "test_folder_id";
    trade::GoogleDriveSync sync(cfg);
    EXPECT_FALSE(sync.available());
}

// Test 5: GoogleDriveSync with JSON missing required fields is not available.
TEST(GoogleDriveSync, UnavailableWithMissingFields) {
    const std::string tmp = "/tmp/test_gd_key_missing_fields.json";
    {
        std::ofstream f(tmp);
        // Valid JSON but missing client_email and private_key
        f << R"({"type":"service_account","project_id":"myproject"})";
    }
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = tmp;
    cfg.root_folder_id = "test_folder_id";
    trade::GoogleDriveSync sync(cfg);
    EXPECT_FALSE(sync.available());
}

// Test 6: GoogleDriveSync with missing root_folder_id is not available,
//         even if key file parses correctly.
TEST(GoogleDriveSync, UnavailableWithEmptyFolderId) {
    const std::string tmp = "/tmp/test_gd_key_no_folder.json";
    {
        std::ofstream f(tmp);
        f << R"({
            "type": "service_account",
            "client_email": "test@project.iam.gserviceaccount.com",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4xBgmxUgBXkY4HSjfDhvGLmBCi9\n-----END RSA PRIVATE KEY-----\n"
        })";
    }
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = tmp;
    cfg.root_folder_id = "";  // empty folder id
    trade::GoogleDriveSync sync(cfg);
    EXPECT_FALSE(sync.available());
}

// Test 7: delete_path on unavailable sync returns false gracefully.
TEST(GoogleDriveSync, DeletePathNotAvailableReturnsFalse) {
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = "/tmp/nonexistent_gd_key2.json";
    cfg.root_folder_id = "test_folder_id";
    trade::GoogleDriveSync sync(cfg);
    EXPECT_FALSE(sync.delete_path("test/file.parquet"));
}

// Test 8: upload_bytes on unavailable sync returns false gracefully.
TEST(GoogleDriveSync, UploadNotAvailableReturnsFalse) {
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = "/tmp/nonexistent_gd_key3.json";
    cfg.root_folder_id = "test_folder_id";
    trade::GoogleDriveSync sync(cfg);
    std::vector<uint8_t> data = {1, 2, 3};
    EXPECT_FALSE(sync.upload_bytes("test/file.parquet", data));
}

// Test 9: download_bytes on unavailable sync returns false gracefully.
TEST(GoogleDriveSync, DownloadNotAvailableReturnsFalse) {
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = "/tmp/nonexistent_gd_key4.json";
    cfg.root_folder_id = "test_folder_id";
    trade::GoogleDriveSync sync(cfg);
    std::vector<uint8_t> out;
    EXPECT_FALSE(sync.download_bytes("test/file.parquet", &out));
    EXPECT_TRUE(out.empty());
}

// Test 10: list_files on unavailable sync returns false gracefully.
TEST(GoogleDriveSync, ListFilesNotAvailableReturnsFalse) {
    trade::GoogleDriveSync::Config cfg;
    cfg.service_account_json_path = "/tmp/nonexistent_gd_key5.json";
    cfg.root_folder_id = "test_folder_id";
    trade::GoogleDriveSync sync(cfg);
    std::vector<std::string> names;
    EXPECT_FALSE(sync.list_files("some/dir", &names));
    EXPECT_TRUE(names.empty());
}

// Test 11: CloudSync delete_paths default impl calls delete_path for each item.
//          Use a subclass that counts calls.
TEST(CloudSync, DeletePathsCallsDeletePathForEach) {
    struct CountingSync : public trade::CloudSync {
        int delete_count = 0;
        bool upload_bytes(const std::string&, const std::vector<uint8_t>&) override { return false; }
        bool download_bytes(const std::string&, std::vector<uint8_t>*) override { return false; }
        bool delete_path(const std::string&) override {
            ++delete_count;
            return true;
        }
        bool list_files(const std::string&, std::vector<std::string>*) override { return false; }
        bool available() const override { return true; }
    };

    CountingSync sync;
    std::vector<std::string> paths = {"a.parquet", "b.parquet", "c.parquet"};
    bool result = sync.delete_paths(paths);
    EXPECT_TRUE(result);
    EXPECT_EQ(sync.delete_count, 3);
}

// Test 12: CloudSync delete_paths returns false if any delete_path fails.
TEST(CloudSync, DeletePathsReturnsFalseOnAnyFailure) {
    struct FailOnSecondSync : public trade::CloudSync {
        int call_count = 0;
        bool upload_bytes(const std::string&, const std::vector<uint8_t>&) override { return false; }
        bool download_bytes(const std::string&, std::vector<uint8_t>*) override { return false; }
        bool delete_path(const std::string&) override {
            ++call_count;
            return call_count != 2;  // fail on 2nd call
        }
        bool list_files(const std::string&, std::vector<std::string>*) override { return false; }
        bool available() const override { return true; }
    };

    FailOnSecondSync sync;
    std::vector<std::string> paths = {"a.parquet", "b.parquet", "c.parquet"};
    bool result = sync.delete_paths(paths);
    EXPECT_FALSE(result);
    EXPECT_EQ(sync.call_count, 3);  // all paths attempted
}

} // namespace
