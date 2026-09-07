/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#include "ua_server_internal.h"
#include "ua_config_default.h"
#include "ua_log_stdout.h"
#include "ua_plugin_log.h"
#include "testing_networklayers.h"

#include <stdio.h>

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
LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    UA_ByteString verifyBuf;
    UA_ByteString_init(&verifyBuf);
    UA_Connection c = createDummyConnection(65535, &verifyBuf);
    UA_ServerConfig *config = UA_ServerConfig_new_default();
    UA_Server *server = UA_Server_new(config);
    if (server == NULL) {
        UA_LOG_ERROR(UA_Log_Stdout, UA_LOGCATEGORY_SERVER,
                     "Could not create server instance using UA_Server_new");
        writeFailure();
        return 1;
    }

    // we need to copy the message because it will be freed in the processing function
    UA_ByteString msg = UA_ByteString();
    UA_StatusCode retval = UA_ByteString_allocBuffer(&msg, size);
    if(retval != UA_STATUSCODE_GOOD) {
        writeFailure();
        return (int)retval;
    }
    memcpy(msg.data, data, size);

    UA_Server_processBinaryMessage(server, &c, &msg);

    if (verifyBuf.data && verifyBuf.length > 0) {
        FILE *out = fopen("/tmp/output", "wb");
        if (out) {
            fwrite(verifyBuf.data, 1, verifyBuf.length, out);
            fclose(out);
        } else {
            writeFailure();
        }
    } else {
        writeFailure();
    }

    // if we got an invalid chunk, the message is not deleted, so delete it here
    UA_ByteString_deleteMembers(&msg);
    UA_ByteString_deleteMembers(&verifyBuf);
    UA_Server_run_shutdown(server);
    UA_Server_delete(server);
    UA_ServerConfig_delete(config);
    c.close(&c);
    UA_Connection_deleteMembers(&c);
    return 0;
}
