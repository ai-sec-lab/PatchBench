#include <wolfssl/options.h>
#include <wolfssl/wolfcrypt/asn.h>
#include <fuzzers/shared.h>

#include <stdio.h>

static void writeFailure(void) {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

FUZZER_INITIALIZE_HEADER
FUZZER_INITIALIZE_FOOTER_1
FUZZER_INITIALIZE_FOOTER_2

FUZZER_RUN_HEADER
{
    OcspResponse resp;
    OcspEntry single;
    CertStatus status;
    InitOcspResponse(&resp, &single, &status, data, size, NULL);
    int decode_rc = OcspResponseDecode(&resp, NULL, NULL, 1);
    FreeOcspResponse(&resp);

    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fprintf(f, "size=%zu\ndecode_rc=%d\n", size, decode_rc);
        fclose(f);
    } else {
        writeFailure();
    }
}
FUZZER_RUN_FOOTER
