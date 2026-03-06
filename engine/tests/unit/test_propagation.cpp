#include <gtest/gtest.h>
#include "trade/signal/propagation.h"
#include <fstream>
#include <spdlog/spdlog.h>

using namespace trade;

// minimal graph JSON shared by tests (name_zh in ASCII to avoid JSON escape issues)
static const char* kTestJson = R"({
    "version": "1.0",
    "nodes": [
        {"id": "SW_Electronics", "sw_code": 5, "name_zh": "Electronics"},
        {"id": "SW_NonFerrousMetal", "sw_code": 4, "name_zh": "NonFerrousMetal"},
        {"id": "SW_Computer", "sw_code": 23, "name_zh": "Computer"}
    ],
    "edges": [
        {"source": "SW_NonFerrousMetal", "target": "SW_Electronics",
         "relation": "upstream_supply", "weight": 0.75, "direction": 1, "typical_days": 8},
        {"source": "SW_Electronics", "target": "SW_Computer",
         "relation": "upstream_supply", "weight": 0.55, "direction": 1, "typical_days": 10}
    ],
    "event_mappings": {
        "semiconductor_policy": [
            {"sector": "SW_Electronics", "score": 0.9},
            {"sector": "SW_NonFerrousMetal", "score": 0.6}
        ]
    }
})";

TEST(PropagationTest, LoadFromJson) {
    std::string tmp = "/tmp/test_propagation_graph.json";
    {
        std::ofstream f(tmp);
        f << kTestJson;
    }

    EventPropagator prop;
    EXPECT_TRUE(prop.load(tmp));
    EXPECT_TRUE(prop.ready());

    auto events = prop.available_events();
    ASSERT_EQ(events.size(), 1u);
    EXPECT_EQ(events[0], "semiconductor_policy");
}

TEST(PropagationTest, PropagateEvent) {
    std::string tmp = "/tmp/test_propagation_graph2.json";
    {
        std::ofstream f(tmp);
        f << kTestJson;
    }

    EventPropagator prop;
    prop.load(tmp);
    auto results = prop.propagate_event("semiconductor_policy", 2);

    // Should have Electronics(primary 0.9), NonFerrousMetal(primary 0.6), Computer(secondary)
    ASSERT_GE(results.size(), 2u);

    // Highest score should be Electronics (0.9)
    EXPECT_EQ(results[0].sector, SWIndustry::kElectronics);
    EXPECT_NEAR(results[0].score, 0.9f, 0.01f);

    // NonFerrousMetal should be in results
    bool found_nonferous = false;
    for (const auto& r : results) {
        if (r.sector == SWIndustry::kNonFerrousMetal) found_nonferous = true;
    }
    EXPECT_TRUE(found_nonferous);
}

TEST(PropagationTest, SecondaryPropagationReachesComputer) {
    std::string tmp = "/tmp/test_propagation_graph3.json";
    {
        std::ofstream f(tmp);
        f << kTestJson;
    }

    EventPropagator prop;
    prop.load(tmp);
    auto results = prop.propagate_event("semiconductor_policy", 2);

    // Computer is 2-hop from Electronics -> Computer
    bool found_computer = false;
    for (const auto& r : results) {
        if (r.sector == SWIndustry::kComputer) {
            found_computer = true;
            EXPECT_EQ(r.hop, 2);
            EXPECT_GT(r.score, 0.0f);
        }
    }
    EXPECT_TRUE(found_computer);
}

TEST(PropagationTest, UnknownEventReturnsEmpty) {
    std::string tmp = "/tmp/test_propagation_graph4.json";
    {
        std::ofstream f(tmp);
        f << kTestJson;
    }

    EventPropagator prop;
    prop.load(tmp);
    auto r = prop.propagate_event("unknown_event");
    EXPECT_TRUE(r.empty());
}

TEST(PropagationTest, NotLoadedReturnsEmpty) {
    EventPropagator prop;
    EXPECT_FALSE(prop.ready());
    auto r = prop.propagate_event("semiconductor_policy");
    EXPECT_TRUE(r.empty());
}

TEST(PropagationTest, MissingFileReturnsFalse) {
    EventPropagator prop;
    EXPECT_FALSE(prop.load("/tmp/nonexistent_graph_12345.json"));
    EXPECT_FALSE(prop.ready());
}
