#include <stdio.h>
#include <stddef.h>
#define main tv_generated_main
#include "generated.c"
#undef main

/* Values come from this target's actual emitted declarations, not a size model. */
int main(void) {
    printf("{\"tv_region\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":{"
           "\"storage\":%zu,\"capacity\":%zu,\"instance\":%zu,\"live_size\":%zu,\"live_alignment\":%zu,\"occupied\":%zu}},"
           "\"tv_block\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":{"
           "\"origin\":%zu,\"instance\":%zu,\"length\":%zu,\"alignment\":%zu}},"
           "\"tv_allocation\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":{\"tag\":%zu,\"payload\":%zu,\"payload.block\":%zu}},"
           "\"tv_str\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":{\"data\":%zu,\"len\":%zu}},"
           "\"tv_s_Allocation\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":{\"tv_tag\":%zu,\"tv_payload\":%zu,\"tv_payload.tv_m_Granted\":%zu}},"
           "\"tv_s_ByteRead\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":{\"tv_tag\":%zu,\"tv_payload\":%zu,\"tv_payload.tv_m_Value\":%zu}},"
           "\"tv_s_ByteWrite\":{\"size\":%zu,\"alignment\":%zu,\"offsets\":{\"tv_tag\":%zu,\"tv_payload\":%zu,\"tv_payload.tv_empty\":%zu}}}\n",
           sizeof(tv_region), _Alignof(tv_region), offsetof(tv_region, storage), offsetof(tv_region, capacity),
           offsetof(tv_region, instance), offsetof(tv_region, live_size), offsetof(tv_region, live_alignment), offsetof(tv_region, occupied),
           sizeof(tv_block), _Alignof(tv_block), offsetof(tv_block, origin), offsetof(tv_block, instance), offsetof(tv_block, length), offsetof(tv_block, alignment),
           sizeof(tv_allocation), _Alignof(tv_allocation), offsetof(tv_allocation, tag), offsetof(tv_allocation, payload), offsetof(tv_allocation, payload.block),
           sizeof(tv_str), _Alignof(tv_str), offsetof(tv_str, data), offsetof(tv_str, len),
           sizeof(struct tv_s_Allocation), _Alignof(struct tv_s_Allocation), offsetof(struct tv_s_Allocation, tv_tag),
           offsetof(struct tv_s_Allocation, tv_payload), offsetof(struct tv_s_Allocation, tv_payload.tv_m_Granted),
           sizeof(struct tv_s_ByteRead), _Alignof(struct tv_s_ByteRead), offsetof(struct tv_s_ByteRead, tv_tag),
           offsetof(struct tv_s_ByteRead, tv_payload), offsetof(struct tv_s_ByteRead, tv_payload.tv_m_Value),
           sizeof(struct tv_s_ByteWrite), _Alignof(struct tv_s_ByteWrite), offsetof(struct tv_s_ByteWrite, tv_tag),
           offsetof(struct tv_s_ByteWrite, tv_payload), offsetof(struct tv_s_ByteWrite, tv_payload.tv_empty));
    return 0;
}
