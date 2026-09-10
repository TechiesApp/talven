/* Optional static-text output, retained from the reference C11 contract. */

#include <errno.h>
#include <unistd.h>
static int32_t tv_console_print(tv_str text) {
    size_t offset = 0;
    while (offset < text.len) {
        size_t count = text.len - offset;
        if (count > 16384) { count = 16384; }
        ssize_t written = write(STDOUT_FILENO, text.data + offset, count);
        if (written < 0) {
            if (errno == EINTR) { continue; }
            return INT32_C(1);
        }
        if (written == 0) { return INT32_C(1); }
        offset += (size_t)written;
    }
    return INT32_C(0);
}
