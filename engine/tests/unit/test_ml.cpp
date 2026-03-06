#include <gtest/gtest.h>
#include <LightGBM/c_api.h>

#include <cstring>
#include <vector>

// =============================================================================
// Placeholder tests to verify LightGBM library can be linked
// =============================================================================

TEST(MLTest, LightGBMLibraryLinked) {
    // Verify we can call a LightGBM C API function without crashing.
    // LGBM_GetLastError returns a const char* describing the last error.
    // Older LightGBM returns "" on no error; newer versions return
    // "Everything is fine". Either is acceptable.
    const char* last_error = LGBM_GetLastError();
    ASSERT_NE(last_error, nullptr);
    const bool no_error = (std::strlen(last_error) == 0u ||
                           std::strcmp(last_error, "Everything is fine") == 0);
    EXPECT_TRUE(no_error) << "Unexpected error on init: " << last_error;
}

TEST(MLTest, LightGBMCreateDatasetFromMat) {
    // Create a simple dataset using the C API to verify linkage.
    // We'll create a minimal dataset with 3 samples, 2 features.
    const int num_data = 3;
    const int num_features = 2;

    // Feature data (row-major: [sample0_f0, sample0_f1, sample1_f0, ...])
    std::vector<double> data = {
        1.0, 2.0,   // sample 0
        3.0, 4.0,   // sample 1
        5.0, 6.0,   // sample 2
    };

    // Labels
    std::vector<float> labels = {0.0f, 1.0f, 0.0f};

    DatasetHandle dataset = nullptr;
    int result = LGBM_DatasetCreateFromMat(
        data.data(),
        C_API_DTYPE_FLOAT64,
        num_data,
        num_features,
        1,  // is_row_major
        "",  // parameters
        nullptr,  // reference dataset
        &dataset);

    EXPECT_EQ(result, 0) << "Failed to create dataset: " << LGBM_GetLastError();

    if (dataset != nullptr) {
        // Set labels
        result = LGBM_DatasetSetField(
            dataset, "label", labels.data(), num_data, C_API_DTYPE_FLOAT32);
        EXPECT_EQ(result, 0) << "Failed to set labels: " << LGBM_GetLastError();

        // Verify number of data points
        int num_data_out = 0;
        result = LGBM_DatasetGetNumData(dataset, &num_data_out);
        EXPECT_EQ(result, 0);
        EXPECT_EQ(num_data_out, num_data);

        // Verify number of features
        int num_features_out = 0;
        result = LGBM_DatasetGetNumFeature(dataset, &num_features_out);
        EXPECT_EQ(result, 0);
        EXPECT_EQ(num_features_out, num_features);

        // Clean up
        LGBM_DatasetFree(dataset);
    }
}

TEST(MLTest, LightGBMCreateDatasetFloat32) {
    // Create a dataset using float32 data to verify the alternate type
    const int n_rows = 10;
    const int n_cols = 3;
    std::vector<float> data(n_rows * n_cols);
    std::vector<float> labels(n_rows);

    // Fill with simple data
    for (int i = 0; i < n_rows; ++i) {
        for (int j = 0; j < n_cols; ++j) {
            data[i * n_cols + j] = static_cast<float>(i + j);
        }
        labels[i] = static_cast<float>(i % 2);
    }

    DatasetHandle dataset = nullptr;
    int result = LGBM_DatasetCreateFromMat(
        data.data(), C_API_DTYPE_FLOAT32, n_rows, n_cols, 1,
        "max_bin=255", nullptr, &dataset);
    EXPECT_EQ(result, 0) << "Failed to create float32 dataset: " << LGBM_GetLastError();

    if (dataset != nullptr) {
        result = LGBM_DatasetSetField(dataset, "label", labels.data(), n_rows, C_API_DTYPE_FLOAT32);
        EXPECT_EQ(result, 0);

        LGBM_DatasetFree(dataset);
    }
}
