/*
 * xslt.c: libFuzzer target for XSLT stylesheets
 *
 * See Copyright for the status of this software.
 */

#include "fuzz.h"
#include <libxml/globals.h>
#include <stdio.h>
#include <string.h>

static void writeFailure(void) {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

int
LLVMFuzzerInitialize(int *argc_p ATTRIBUTE_UNUSED,
                     char ***argv_p ATTRIBUTE_UNUSED) {
    return xsltFuzzXsltInit();
}

int
LLVMFuzzerTestOneInput(const char *data, size_t size) {
    xmlChar *result = xsltFuzzXslt(data, size);

    if (result) {
        size_t len = strlen((const char *)result);
        if (len > 0) {
            FILE *f = fopen("/tmp/output", "wb");
            if (f) {
                fwrite(result, 1, len, f);
                fclose(f);
            } else {
                writeFailure();
            }
        } else {
            writeFailure();
        }
    } else {
        writeFailure();
    }

    xmlFree(result);

    return 0;
}
