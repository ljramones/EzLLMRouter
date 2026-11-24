/* Bounded history-window regression for upstream zstd PR 5023. */
#define ZSTD_STATIC_LINKING_ONLY
#include "zstd.h"
#include "decompress/zstd_decompress_internal.h"
#include <stdio.h>
#include <string.h>

void ZSTD_checkContinuity(ZSTD_DCtx* dctx, const void* dst, size_t dstSize);

int main(void) {
    char arena[8192] = {0};
    size_t prefixes[] = {256, 1024, 1536};
    unsigned i;
    for (i = 0; i < sizeof(prefixes) / sizeof(prefixes[0]); ++i) {
        ZSTD_DCtx* ctx = ZSTD_createDCtx();
        size_t expected = prefixes[i] < 1024 ? 1024 - prefixes[i] : 0;
        size_t observed;
        if (!ctx) return 2;
        ctx->prefixStart = arena + 2048;
        ctx->virtualStart = arena + 1024;
        ctx->previousDstEnd = (const char*)ctx->prefixStart + prefixes[i];
        ctx->decodedSize = 2048;
        ctx->fParams.windowSize = 1024;
        ctx->isFrameDecompression = 1;
        ZSTD_checkContinuity(ctx, ctx->previousDstEnd, 128);
        observed = (size_t)((const char*)ctx->prefixStart - (const char*)ctx->virtualStart);
        printf("prefix=%zu external_history=%zu expected=%zu\n", prefixes[i], observed, expected);
        ZSTD_freeDCtx(ctx);
        if (observed != expected) return 1;
    }
    return 0;
}
