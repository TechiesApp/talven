#include <limits.h>
#include <stdio.h>
#include <string.h>
#define main tv_generated_main
#include "generated.c"
#undef main
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "source-ledger:%d\n", __LINE__); exit(41); } } while (0)
#ifndef TEST_CAPACITY
#define TEST_CAPACITY 32
#endif

static struct {
    uint8_t bytes[TEST_CAPACITY];
    uint64_t instance;
    bool live;
    size_t size, alignment;
    unsigned requests, releases, reads, writes, initialized;
} ledger;
static int32_t planned_size, planned_alignment, planned_index, planned_value;
static int32_t fail_at = -1;
static uint32_t fault_calls;
static bool saturated, fault_once;
static tv_region *active_origin;

bool tv_region_test_fault(uint32_t step) {
    REQUIRE(step == fault_calls);
    fault_calls += 1;
    return fail_at >= 0 && step == (uint32_t)fail_at;
}

static void observe(tv_region *region) {
    REQUIRE(region == active_origin && region->capacity == TEST_CAPACITY);
    REQUIRE(region->instance == ledger.instance && region->occupied == ledger.live);
    REQUIRE(region->live_size == ledger.size && region->live_alignment == ledger.alignment);
    REQUIRE(((uintptr_t)region->storage % 16) == 0);
    REQUIRE(memcmp(region->storage, ledger.bytes, TEST_CAPACITY) == 0);
}

void tv_region_source_event(uint32_t operation, tv_region *region, const tv_block *block,
                            int32_t first, int32_t second, uint32_t tag, int32_t value) {
    if (operation == 0) {
        REQUIRE(ledger.initialized == 0 && first == TEST_CAPACITY && second == 0);
        REQUIRE(region->capacity == TEST_CAPACITY && region->instance == 0 && !region->occupied);
        REQUIRE(region->live_size == 0 && region->live_alignment == 0);
        active_origin = region;
        ledger.initialized = 1;
        memset(ledger.bytes, 0xa5, TEST_CAPACITY);
        memset(region->storage, 0xa5, TEST_CAPACITY); /* Trusted fixture, never source control. */
        if (saturated) { region->instance = ledger.instance = UINT64_MAX - 1; }
        observe(region);
        return;
    }
    REQUIRE(ledger.initialized == 1 && active_origin == region);
    if (operation == 1) {
        REQUIRE(first == planned_size && second == planned_alignment);
        bool valid = first > 0 && (second == 1 || second == 2 || second == 4 || second == 8 || second == 16);
        bool space = valid && first <= TEST_CAPACITY && !ledger.live && ledger.instance != UINT64_MAX;
        uint32_t expected = !valid ? 1 : !space ? 2 : 0;
        if (space) {
            ledger.instance += 1;
#ifdef TV_REGION_TEST_FAULT
            bool failed = fail_at >= 0 && fail_at <= first + 1;
            REQUIRE(fault_calls == (failed ? (uint32_t)fail_at + 1 : (uint32_t)first + 2));
#else
            bool failed = false;
            REQUIRE(fault_calls == 0);
#endif
            size_t initialized = failed ? (fail_at <= 1 ? 0 : (size_t)fail_at - 1) : (size_t)first;
            memset(ledger.bytes, 0, initialized);
            if (failed) { expected = 2; }
            else { ledger.live = true; ledger.size = (size_t)first; ledger.alignment = (size_t)second; }
        } else { REQUIRE(fault_calls == 0); }
        REQUIRE(tag == expected && ((block != NULL) == (expected == 0)));
        if (block) {
            REQUIRE(block->origin == region && block->instance == ledger.instance);
            REQUIRE(block->length == ledger.size && block->alignment == ledger.alignment);
        }
        ledger.requests += 1;
        fault_calls = 0;
        if (fault_once) { fail_at = -1; }
    } else {
        REQUIRE(block != NULL && ledger.live && block->origin == region);
        REQUIRE(block->instance == ledger.instance && block->length == ledger.size && block->alignment == ledger.alignment);
        if (operation == 2) {
            REQUIRE(value == 0);
            ledger.live = false;
            ledger.size = ledger.alignment = 0;
            ledger.releases += 1;
        } else if (operation == 3) {
            bool wrote = planned_index >= 0 && (size_t)planned_index < ledger.size && planned_value >= 0 && planned_value <= 255;
            REQUIRE(first == (wrote ? planned_index : 0));
            bool valid = first >= 0 && (size_t)first < ledger.size;
            REQUIRE(tag == (valid ? 0u : 1u));
            if (valid) { REQUIRE(value == ledger.bytes[(size_t)first]); }
            ledger.reads += 1;
        } else if (operation == 4) {
            REQUIRE(first == planned_index && second == planned_value);
            uint32_t expected = first < 0 || (size_t)first >= ledger.size ? 1 : second < 0 || second > 255 ? 2 : 0;
            REQUIRE(tag == expected);
            if (expected == 0) { ledger.bytes[(size_t)first] = (uint8_t)second; }
            ledger.writes += 1;
        } else { REQUIRE(false); }
    }
    observe(region);
}

static void start(int32_t size, int32_t alignment, int32_t index, int32_t value) {
    memset(&ledger, 0, sizeof(ledger));
    active_origin = NULL;
    fault_calls = 0;
    planned_size = size; planned_alignment = alignment; planned_index = index; planned_value = value;
}

static bool valid_request(int32_t size, int32_t alignment) {
    return size > 0 && (alignment == 1 || alignment == 2 || alignment == 4 || alignment == 8 || alignment == 16);
}

static void probe(int32_t size, int32_t alignment, int32_t index, int32_t value) {
    start(size, alignment, index, value);
    bool valid = valid_request(size, alignment), granted = valid && size <= TEST_CAPACITY;
    int32_t expected = !valid ? -10 : !granted ? -20 : index < 0 || index >= size ? -30 : value < 0 || value > 255 ? -40 : value;
    REQUIRE(tv_f_probe(size, alignment, index, value) == expected);
    REQUIRE(ledger.initialized == 1 && ledger.requests == 1 && !ledger.live);
    REQUIRE(ledger.releases == (unsigned)granted && ledger.reads == (unsigned)granted && ledger.writes == (unsigned)granted);
}

int main(void) {
    int32_t sizes[] = {INT32_MIN, -1, 0, 1, TEST_CAPACITY, TEST_CAPACITY + 1, INT32_MAX};
    int32_t alignments[] = {INT32_MIN, -1, 0, 1, 2, 3, 4, 8, 16, 17, INT32_MAX};
    int32_t indices[] = {INT32_MIN, -1, 0, TEST_CAPACITY - 1, TEST_CAPACITY, INT32_MAX};
    int32_t values[] = {INT32_MIN, -1, 0, 1, 255, 256, INT32_MAX};
    for (unsigned s = 0; s < sizeof(sizes)/sizeof(sizes[0]); ++s) {
        for (unsigned a = 0; a < sizeof(alignments)/sizeof(alignments[0]); ++a) {
            probe(sizes[s], alignments[a], 0, 42);
            bool valid = valid_request(sizes[s], alignments[a]);
            bool granted = valid && sizes[s] <= TEST_CAPACITY;
            start(sizes[s], alignments[a], 0, 0);
            REQUIRE(tv_f_rewrap(sizes[s], alignments[a]) == (!valid ? -10 : !granted ? -20 : 0));
            REQUIRE(ledger.requests == 1 && ledger.releases == (unsigned)granted && !ledger.live);
            start(sizes[s], alignments[a], 0, 0);
            REQUIRE(tv_f_reuse(sizes[s], alignments[a]) == (!valid ? -10 : !granted ? -20 : 0));
            REQUIRE(ledger.requests == (granted ? 2u : 1u) && ledger.releases == (granted ? 2u : 0u) && !ledger.live);
        }
    }
    for (unsigned i = 0; i < sizeof(indices)/sizeof(indices[0]); ++i) {
        for (unsigned v = 0; v < sizeof(values)/sizeof(values[0]); ++v) {
            probe(TEST_CAPACITY, 16, indices[i], values[v]);
        }
    }
#ifdef TV_REGION_TEST_FAULT
    int32_t counts[] = {1, TEST_CAPACITY};
    for (unsigned n = 0; n < sizeof(counts)/sizeof(counts[0]); ++n) {
        for (int32_t fault = 0; fault <= counts[n] + 1; ++fault) {
            start(counts[n], 16, 0, 0);
            fail_at = fault; fault_once = true;
            REQUIRE(tv_f_retry(counts[n], 16) == 0);
            REQUIRE(ledger.requests == 2 && ledger.releases == 1 && ledger.instance == 2 && !ledger.live);
        }
    }
#endif
    fail_at = -1; fault_once = false; saturated = true;
    start(1, 1, 0, 0);
    REQUIRE(tv_f_reuse(1, 1) == -20);
    REQUIRE(ledger.requests == 2 && ledger.releases == 1 && ledger.instance == UINT64_MAX && !ledger.live);
    return 0;
}
