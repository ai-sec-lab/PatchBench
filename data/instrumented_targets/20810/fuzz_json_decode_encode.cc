/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 *
 *    Copyright 2018 (c) Fraunhofer IOSB (Author: Julius Pfrommer)
 */

#include <open62541/types.h>
#include <open62541/types_generated_handling.h>
#include "ua_types_encoding_json.h"

#include <stdio.h>

static void writeFailure() {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

/* The round-trip below only reaches its final encoding for input that is
   already valid OPC-UA JSON, which AFL seeds essentially never are -- every
   sampled input bailed at the first UA_decodeJson. Rather than collapse all of
   those to the sentinel, record which stage rejected the input and the
   StatusCode it returned. Both are derived from the input, so this stays
   deterministic and still distinguishes one seed from another. */
static void writeStage(const char *stage, UA_StatusCode code) {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fprintf(f, "stage=%s status=0x%08X\n", stage, (unsigned)code);
        fclose(f);
    } else {
        writeFailure();
    }
}

/* Decode a message, then encode, decode, encode.
 * The two encodings must be bit-equal. */
extern "C" int
LLVMFuzzerTestOneInput(uint8_t *data, size_t size) {
    UA_ByteString buf;
    buf.data = (UA_Byte*)data;
    buf.length = size;

    UA_Variant value;
    UA_Variant_init(&value);

    UA_StatusCode retval = UA_decodeJson(&buf, &value, &UA_TYPES[UA_TYPES_VARIANT]);
    if(retval != UA_STATUSCODE_GOOD) {
        writeStage("decode1", retval);
        return 0;
    }

    size_t jsonSize = UA_calcSizeJson(&value, &UA_TYPES[UA_TYPES_VARIANT],
                                      NULL, 0, NULL, 0, true);

    UA_ByteString buf2 = UA_BYTESTRING_NULL;
    retval = UA_ByteString_allocBuffer(&buf2, jsonSize);
    if(retval != UA_STATUSCODE_GOOD) {
        UA_Variant_deleteMembers(&value);
        writeStage("alloc1", retval);
        return 0;
    }

    uint8_t *bufPos = buf2.data;
    const uint8_t *bufEnd = &buf2.data[buf2.length];
    retval = UA_encodeJson(&value, &UA_TYPES[UA_TYPES_VARIANT],
                           &bufPos, &bufEnd, NULL, 0, NULL, 0, true);
	UA_Variant_deleteMembers(&value);
	if(retval != UA_STATUSCODE_GOOD || bufPos != bufEnd) {
		UA_ByteString_deleteMembers(&buf2);
		writeStage("encode1", retval);
		return 0;
	}

    UA_Variant value2;
    UA_Variant_init(&value2);

    retval = UA_decodeJson(&buf2, &value2, &UA_TYPES[UA_TYPES_VARIANT]);
    if(retval != UA_STATUSCODE_GOOD) {
		UA_ByteString_deleteMembers(&buf2);
		writeStage("decode2", retval);
		return 0;
	}

    UA_ByteString buf3 = UA_BYTESTRING_NULL;
    retval = UA_ByteString_allocBuffer(&buf3, jsonSize);
    if(retval != UA_STATUSCODE_GOOD) {
        UA_Variant_deleteMembers(&value2);
        UA_ByteString_deleteMembers(&buf2);
        writeStage("alloc2", retval);
        return 0;
    }

    bufPos = buf3.data;
    bufEnd = &buf3.data[buf3.length];
    retval = UA_encodeJson(&value2, &UA_TYPES[UA_TYPES_VARIANT],
                           &bufPos, &bufEnd, NULL, 0, NULL, 0, true);
	UA_Variant_deleteMembers(&value2);
	if(retval != UA_STATUSCODE_GOOD) {
		UA_ByteString_deleteMembers(&buf2);
		UA_ByteString_deleteMembers(&buf3);
		writeStage("encode2", retval);
		return 0;
	}

    {
        size_t enc3Len = (size_t)(bufPos - buf3.data);
        if (buf3.data && enc3Len > 0) {
            FILE *of = fopen("/tmp/output", "wb");
            if (of) {
                fwrite(buf3.data, 1, enc3Len, of);
                fclose(of);
            } else {
                writeFailure();
            }
        } else {
            writeFailure();
        }
    }

    UA_assert(buf2.length == buf3.length);
    UA_assert(memcmp(buf2.data, buf3.data, buf2.length) == 0);
    UA_ByteString_deleteMembers(&buf2);
    UA_ByteString_deleteMembers(&buf3);
    return 0;
}
