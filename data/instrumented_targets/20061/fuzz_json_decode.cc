/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 *
 *    Copyright 2018 (c) Fraunhofer IOSB (Author: Lukas Meling)
 */


#include <open62541/types.h>
#include <open62541/types_generated_handling.h>
#include "ua_types_encoding_json.h"

#include <stdio.h>
#include <stdlib.h>

static void writeFailure() {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

/*
** Main entry point.  The fuzzer invokes this function with each
** fuzzed input.
*/
extern "C" int
LLVMFuzzerTestOneInput(uint8_t *data, size_t size) {
    UA_ByteString buf;
    buf.data = (UA_Byte*)data;
    buf.length = size;

    UA_Variant out;
    UA_Variant_init(&out);

    UA_StatusCode retval = UA_decodeJson(&buf, &out, &UA_TYPES[UA_TYPES_VARIANT]);
    if(retval == UA_STATUSCODE_GOOD) {
        size_t encSize = UA_calcSizeJson(&out, &UA_TYPES[UA_TYPES_VARIANT],
                                         NULL, 0, NULL, 0, UA_TRUE);
        if (encSize > 0) {
            uint8_t *enc = (uint8_t *)malloc(encSize);
            if (enc) {
                uint8_t *pos = enc;
                const uint8_t *end = enc + encSize;
                UA_StatusCode encRet = UA_encodeJson(&out, &UA_TYPES[UA_TYPES_VARIANT],
                                                    &pos, &end, NULL, 0, NULL, 0, UA_TRUE);
                if (encRet == UA_STATUSCODE_GOOD) {
                    FILE *of = fopen("/tmp/output", "wb");
                    if (of) {
                        fwrite(enc, 1, (size_t)(pos - enc), of);
                        fclose(of);
                    } else {
                        writeFailure();
                    }
                } else {
                    writeFailure();
                }
                free(enc);
            } else {
                writeFailure();
            }
        } else {
            writeFailure();
        }
        UA_Variant_deleteMembers(&out);
    } else {
        writeFailure();
    }

    return 0;
}
