#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>

#include <blosc2.h>

#ifdef __cplusplus
extern "C" {
#endif

static void writeFailure(void) {
  FILE *output = fopen("/tmp/output", "wb");
  if (output) {
    fwrite("failed to save /tmp/output", 1, 26, output);
    fclose(output);
  }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  const char *compressors[] = { "blosclz", "lz4", "lz4hc", "snappy", "zlib", "zstd" };
  int32_t i = 0, dsize = 0, filter = BLOSC_BITSHUFFLE;
  int32_t nchunk = 0;
  int decompress_failed = 0;

  blosc_init();
  blosc_set_nthreads(1);

  blosc2_dparams dparams = BLOSC2_DPARAMS_DEFAULTS;
  dparams.nthreads = 1;

  /* Create a super-chunk backed by an in-memory frame */
  blosc2_schunk* schunk = blosc2_schunk_open_sframe((uint8_t *)data, size);
  if (schunk == NULL) {
    writeFailure();
    blosc_destroy();
    return 0;
  }
  /* Don't allow address sanitizer to allocate more than INT32_MAX */
  if (schunk->nbytes >= INT32_MAX) {
    writeFailure();
    blosc2_schunk_free(schunk);
    blosc_destroy();
    return 0;
  }
  /* Decompress data */
  uint8_t *uncompressed_data = (uint8_t *)calloc((size_t)schunk->nbytes+1, 1);
  if (uncompressed_data != NULL) {
    for (i = 0, nchunk = 0; nchunk < schunk->nchunks-1; nchunk++) {
      dsize = blosc2_schunk_decompress_chunk(schunk, nchunk, uncompressed_data + i, schunk->chunksize);
      if (dsize < 0) {
        printf("Decompression error.  Error code: %d\n", dsize);
        decompress_failed = 1;
        break;
      }
      i += dsize;
    }

    if (!decompress_failed && i > 0) {
      FILE *output = fopen("/tmp/output", "wb");
      if (output) {
        size_t written = fwrite(uncompressed_data, 1, (size_t)i, output);
        fclose(output);
        if (written != (size_t)i) {
          writeFailure();
        }
      } else {
        writeFailure();
      }
    } else {
      writeFailure();
    }

    free(uncompressed_data);
  } else {
    writeFailure();
  }

  blosc2_schunk_free(schunk);
  blosc_destroy();
  return 0;
}

#ifdef __cplusplus
}
#endif
