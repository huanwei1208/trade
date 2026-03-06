#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace trade {

// Abstract cloud storage sync interface.
// Implementations: GoogleDriveSync (production), NullCloudSync (testing/local).
class CloudSync {
public:
    virtual ~CloudSync() = default;

    // Upload raw bytes to a cloud path (relative to root).
    virtual bool upload_bytes(const std::string& remote_rel_path,
                              const std::vector<uint8_t>& data) = 0;

    // Download raw bytes from a cloud path.
    virtual bool download_bytes(const std::string& remote_rel_path,
                                std::vector<uint8_t>* out) = 0;

    // Delete a single path.
    virtual bool delete_path(const std::string& remote_rel_path) = 0;

    // Delete multiple paths (default implementation loops over delete_path).
    virtual bool delete_paths(const std::vector<std::string>& paths);

    // List file names (not full paths) in a remote directory.
    virtual bool list_files(const std::string& remote_rel_dir,
                            std::vector<std::string>* names_out) = 0;

    // True if this sync backend is configured and operational.
    virtual bool available() const = 0;
};

// No-op implementation for local-only mode.
class NullCloudSync final : public CloudSync {
public:
    bool upload_bytes(const std::string&, const std::vector<uint8_t>&) override { return false; }
    bool download_bytes(const std::string&, std::vector<uint8_t>*) override { return false; }
    bool delete_path(const std::string&) override { return false; }
    bool list_files(const std::string&, std::vector<std::string>*) override { return false; }
    bool available() const override { return false; }
};

} // namespace trade
