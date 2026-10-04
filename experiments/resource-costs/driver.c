#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifndef TEST_CAPACITY
#define TEST_CAPACITY 32
#endif
_Static_assert(TEST_CAPACITY >= 1 && TEST_CAPACITY <= 4096, "capacity range");
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "resource-costs:%d\n", __LINE__); exit(41); } } while (0)

#ifdef COST_LEDGER
#ifndef TV_REGION_SOURCE_TEST
#error COST_LEDGER requires TV_REGION_SOURCE_TEST
#endif
#define main tv_generated_main
#include "generated.c"
#undef main
#else
extern int32_t tv_f_cycle(int32_t, int32_t, int32_t);
extern int32_t tv_f_reuse(int32_t, int32_t, int32_t);
extern int32_t tv_f_sequential(int32_t, int32_t, int32_t);
#endif

typedef int32_t (*workload_fn)(int32_t, int32_t, int32_t);
static workload_fn const workloads[] = {tv_f_cycle, tv_f_reuse, tv_f_sequential};
typedef struct { int32_t size, alignment, index; } input;
static const input rows[] = {
    {1, 1, 0},
    {TEST_CAPACITY, 16, TEST_CAPACITY - 1},
    {(TEST_CAPACITY + 1) / 2, 2, (TEST_CAPACITY + 1) / 2 - 1},
    {TEST_CAPACITY, 8, 0}
};

#ifdef COST_LEDGER
/* Expectations are built from the public call schedule, never runtime metadata. */
typedef struct { unsigned operation, lifetime; } planned_event;
static struct {
    planned_event events[8];
    unsigned event_count, next, lifetime_count, initialized;
    unsigned reserves, reads, writes, releases;
    size_t backing_bytes, zeroed_bytes;
    input request;
    unsigned workload;
    uint32_t reserve_tag;
    struct {
        tv_region *origin;
        uint8_t bytes[TEST_CAPACITY];
        uint64_t instance, last_released;
        bool live;
        size_t size, alignment;
    } regions[2];
} ledger;

static bool valid_request(input request) {
    return request.size > 0 && (request.alignment == 1 || request.alignment == 2 ||
        request.alignment == 4 || request.alignment == 8 || request.alignment == 16);
}

static void plan_event(unsigned operation, unsigned lifetime) {
    REQUIRE(ledger.event_count < sizeof(ledger.events) / sizeof(ledger.events[0]));
    ledger.events[ledger.event_count++] = (planned_event){operation, lifetime};
}

static void start(unsigned workload, input request) {
    memset(&ledger, 0, sizeof(ledger));
    ledger.request = request;
    ledger.workload = workload;
    ledger.reserve_tag = !valid_request(request) ? TV_INVALID_REQUEST :
        request.size > TEST_CAPACITY ? TV_EXHAUSTED : TV_GRANTED;
    bool granted = ledger.reserve_tag == TV_GRANTED;
    bool in_bounds = request.index >= 0 && request.index < request.size;
    ledger.lifetime_count = workload == 2 && granted && in_bounds ? 2 : 1;
    plan_event(0, 0);
    plan_event(1, 0);
    if (granted) {
        if (workload == 1) { plan_event(4, 0); }
        if (workload != 1 || in_bounds) { plan_event(3, 0); }
        plan_event(2, 0);
        if (workload != 0 && in_bounds) {
            unsigned lifetime = workload == 2 ? 1 : 0;
            if (workload == 2) { plan_event(0, lifetime); }
            plan_event(1, lifetime);
            plan_event(3, lifetime);
            plan_event(2, lifetime);
        }
    }
}

static void observe(unsigned lifetime, tv_region *region) {
    REQUIRE(region == ledger.regions[lifetime].origin);
    REQUIRE(region->capacity == TEST_CAPACITY);
    REQUIRE(region->instance == ledger.regions[lifetime].instance);
    REQUIRE(region->occupied == ledger.regions[lifetime].live);
    REQUIRE(region->live_size == ledger.regions[lifetime].size);
    REQUIRE(region->live_alignment == ledger.regions[lifetime].alignment);
    REQUIRE((uintptr_t)region->storage % 16 == 0);
    REQUIRE(memcmp(region->storage, ledger.regions[lifetime].bytes, TEST_CAPACITY) == 0);
}

void tv_region_source_event(uint32_t operation, tv_region *region, const tv_block *block,
                            int32_t first, int32_t second, uint32_t tag, int32_t value) {
    REQUIRE(ledger.next < ledger.event_count);
    planned_event expected = ledger.events[ledger.next++];
    REQUIRE(operation == expected.operation && region != NULL);
    unsigned lifetime = expected.lifetime;
    if (operation == 0) {
        REQUIRE(lifetime == ledger.initialized && lifetime < ledger.lifetime_count);
        if (lifetime != 0) { REQUIRE(!ledger.regions[lifetime - 1].live); }
        REQUIRE(first == TEST_CAPACITY && second == 0 && tag == 0 && value == 0 && block == NULL);
        REQUIRE(region->capacity == TEST_CAPACITY && region->instance == 0 && !region->occupied);
        REQUIRE(region->live_size == 0 && region->live_alignment == 0);
        REQUIRE(region->storage != NULL && (uintptr_t)region->storage % 16 == 0);
        ledger.regions[lifetime].origin = region;
        memset(ledger.regions[lifetime].bytes, 0xa5, TEST_CAPACITY);
        memset(region->storage, 0xa5, TEST_CAPACITY); /* Trusted test sentinel. */
        ledger.initialized++;
        ledger.backing_bytes += TEST_CAPACITY;
    } else if (operation == 1) {
        REQUIRE(first == ledger.request.size && second == ledger.request.alignment && value == 0);
        REQUIRE(!ledger.regions[lifetime].live && tag == ledger.reserve_tag);
        REQUIRE((block != NULL) == (tag == TV_GRANTED));
        ledger.reserves++;
        if (tag == TV_GRANTED) {
            ledger.regions[lifetime].instance++;
            REQUIRE(ledger.regions[lifetime].instance > ledger.regions[lifetime].last_released);
            ledger.regions[lifetime].live = true;
            ledger.regions[lifetime].size = (size_t)ledger.request.size;
            ledger.regions[lifetime].alignment = (size_t)ledger.request.alignment;
            memset(ledger.regions[lifetime].bytes, 0, (size_t)ledger.request.size);
            ledger.zeroed_bytes += (size_t)ledger.request.size;
        }
    } else {
        REQUIRE(block != NULL && ledger.regions[lifetime].live);
        REQUIRE(block->origin == ledger.regions[lifetime].origin);
        REQUIRE(block->instance == ledger.regions[lifetime].instance);
        REQUIRE(block->length == (size_t)ledger.request.size);
        REQUIRE(block->alignment == (size_t)ledger.request.alignment);
        if (operation == 2) {
            REQUIRE(first == 0 && second == 0 && tag == 0 && value == 0);
            REQUIRE(block->instance != ledger.regions[lifetime].last_released);
            ledger.regions[lifetime].last_released = block->instance;
            ledger.regions[lifetime].live = false;
            ledger.regions[lifetime].size = ledger.regions[lifetime].alignment = 0;
            ledger.releases++;
        } else {
            REQUIRE(first == ledger.request.index);
            bool in_bounds = first >= 0 && first < ledger.request.size;
            if (operation == 3) {
                REQUIRE(second == 0 && tag == (in_bounds ? TV_READ_VALUE : TV_READ_OUT_OF_BOUNDS));
                REQUIRE(value == (in_bounds ? ledger.regions[lifetime].bytes[(size_t)ledger.request.index] : 0));
                ledger.reads++;
            } else {
                REQUIRE(operation == 4 && ledger.workload == 1 && second == 137 &&
                    tag == (in_bounds ? TV_WRITTEN : TV_WRITE_OUT_OF_BOUNDS) && value == 0);
                if (in_bounds) { ledger.regions[lifetime].bytes[(size_t)ledger.request.index] = 137; }
                ledger.writes++;
            }
        }
    }
    if (block != NULL && operation == 1) {
        REQUIRE(block->origin == region && block->instance == ledger.regions[lifetime].instance);
        REQUIRE(block->length == (size_t)ledger.request.size && block->alignment == (size_t)ledger.request.alignment);
    }
    observe(lifetime, region);
}

static void checked_call(unsigned workload, input request, int32_t expected_result) {
    start(workload, request);
    REQUIRE(workloads[workload](request.size, request.alignment, request.index) == expected_result);
    bool granted = ledger.reserve_tag == TV_GRANTED;
    bool in_bounds = request.index >= 0 && request.index < request.size;
    unsigned cycles = granted ? (workload == 0 || !in_bounds ? 1 : 2) : 0;
    REQUIRE(ledger.next == ledger.event_count && ledger.initialized == ledger.lifetime_count);
    REQUIRE(ledger.reserves == (granted ? cycles : 1));
    REQUIRE(ledger.reads == (granted && workload == 1 && !in_bounds ? 0 : cycles));
    REQUIRE(ledger.releases == cycles);
    REQUIRE(ledger.writes == (unsigned)(granted && workload == 1));
    REQUIRE(ledger.backing_bytes == ledger.lifetime_count * TEST_CAPACITY);
    REQUIRE(ledger.zeroed_bytes == (granted ? cycles * (size_t)request.size : 0));
    for (unsigned lifetime = 0; lifetime < ledger.lifetime_count; lifetime++) {
        REQUIRE(!ledger.regions[lifetime].live && ledger.regions[lifetime].size == 0 && ledger.regions[lifetime].alignment == 0);
        REQUIRE(ledger.regions[lifetime].instance == ledger.regions[lifetime].last_released);
    }
}
#else
static void checked_call(unsigned workload, input request, int32_t expected_result) {
    REQUIRE(workloads[workload](request.size, request.alignment, request.index) == expected_result);
}
#endif

static void preflight(void) {
    const input failures[] = {{0, 1, 0}, {-1, 1, 0}, {1, 3, 0}, {1, 32, 0}, {TEST_CAPACITY + 1, 1, 0}};
    for (unsigned workload = 0; workload < 3; workload++) {
        for (unsigned row = 0; row < sizeof(failures) / sizeof(failures[0]); row++) {
            checked_call(workload, failures[row], row == 4 ? -20 : -10);
        }
        checked_call(workload, (input){TEST_CAPACITY, 16, -1}, -30);
        checked_call(workload, (input){TEST_CAPACITY, 16, TEST_CAPACITY}, -30);
        for (unsigned row = 0; row < 4; row++) { checked_call(workload, rows[row], 0); }
    }
}

#ifdef COST_LEDGER
int main(void) {
    preflight();
    /* Repeat the fixed successful schedule to catch accidental state retention. */
    for (unsigned workload = 0; workload < 3; workload++) {
        for (unsigned row = 0; row < 4; row++) { checked_call(workload, rows[row], 0); }
    }
    return 0;
}
#else
static uint64_t parse_number(const char *text, uint64_t maximum) {
    REQUIRE(text != NULL && *text != '\0');
    uint64_t value = 0;
    for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
        REQUIRE(*p >= '0' && *p <= '9');
        unsigned digit = (unsigned)(*p - '0');
        REQUIRE(value <= maximum / 10 && (value < maximum / 10 || digit <= maximum % 10));
        value = value * 10 + digit;
    }
    return value;
}

static uint64_t nanoseconds(struct timespec time) {
    REQUIRE(time.tv_sec >= 0 && time.tv_nsec >= 0 && time.tv_nsec < 1000000000L);
    REQUIRE((uint64_t)time.tv_sec <= (UINT64_MAX - (uint64_t)time.tv_nsec) / UINT64_C(1000000000));
    return (uint64_t)time.tv_sec * UINT64_C(1000000000) + (uint64_t)time.tv_nsec;
}

int main(int argc, char **argv) {
    REQUIRE(argc == 3);
    unsigned workload = (unsigned)parse_number(argv[1], 2);
    uint64_t iterations = parse_number(argv[2], 10000000);
    REQUIRE(iterations >= 1 && iterations % 4 == 0);
    preflight();
    struct timespec resolution, begin, end;
    REQUIRE(clock_getres(CLOCK_MONOTONIC, &resolution) == 0);
    uint64_t resolution_ns = nanoseconds(resolution);
    REQUIRE(resolution_ns > 0);
    workload_fn selected = workloads[workload];
    int64_t sum = 0, checksum = 0;
    uint32_t nonzero = 0;
    REQUIRE(clock_gettime(CLOCK_MONOTONIC, &begin) == 0);
    for (uint64_t iteration = 0; iteration < iterations; iteration++) {
        unsigned row = (unsigned)(iteration % 4);
        int32_t result = selected(rows[row].size, rows[row].alignment, rows[row].index);
        sum += result;
        nonzero |= (uint32_t)result;
        checksum += (int64_t)result + row + 1;
    }
    REQUIRE(clock_gettime(CLOCK_MONOTONIC, &end) == 0);
    uint64_t start_ns = nanoseconds(begin), end_ns = nanoseconds(end);
    REQUIRE(end_ns >= start_ns && sum == 0 && nonzero == 0);
    REQUIRE(checksum == (int64_t)(iterations / 4 * 10));
    printf("{\"workload\":%u,\"iterations\":%" PRIu64 ",\"checksum\":%" PRId64
           ",\"elapsed_ns\":%" PRIu64 ",\"resolution_ns\":%" PRIu64 "}\n",
           workload, iterations, checksum, end_ns - start_ns, resolution_ns);
    return 0;
}
#endif
