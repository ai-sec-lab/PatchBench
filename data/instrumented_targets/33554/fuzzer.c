//
//  Wasm3 - high performance WebAssembly interpreter written in C.
//
//  Copyright © 2019 Steven Massey, Volodymyr Shymanskyy.
//  All rights reserved.
//

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

#include "wasm3.h"

#define FATAL(...) __builtin_trap()

static void writeFailure(void) {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    M3Result parse_result = m3Err_none;
    M3Result load_result = m3Err_none;
    M3Result find_result = m3Err_none;
    int env_ok = 0;
    int runtime_ok = 0;
    int module_ok = 0;
    int load_ok = 0;
    int fib_found = 0;

    if (size < 8 || size > 256*1024) {
        writeFailure();
        return 0;
    }

    IM3Environment env = m3_NewEnvironment ();
    if (env) {
        env_ok = 1;
        IM3Runtime runtime = m3_NewRuntime (env, 128, NULL);
        if (runtime) {
            runtime_ok = 1;
            IM3Module module = NULL;
            parse_result = m3_ParseModule (env, &module, data, size);
            if (module) {
                module_ok = 1;
                load_result = m3_LoadModule (runtime, module);
                if (load_result == 0) {
                    load_ok = 1;
                    IM3Function f = NULL;
                    find_result = m3_FindFunction (&f, runtime, "fib");
                    if (find_result == 0 && f != NULL)
                        fib_found = 1;
                    /* TODO:
                    if (f) {
                        m3_CallV (f, 10);
                    }*/
                } else {
                    m3_FreeModule (module);
                }
            }

            m3_FreeRuntime(runtime);
        }
        m3_FreeEnvironment(env);
    }

    {
        FILE *out = fopen("/tmp/output", "wb");
        if (out) {
            fprintf(out,
                "size=%zu\n"
                "env_ok=%d\n"
                "runtime_ok=%d\n"
                "module_ok=%d\n"
                "load_ok=%d\n"
                "fib_found=%d\n"
                "parse_result=%s\n"
                "load_result=%s\n"
                "find_result=%s\n",
                size, env_ok, runtime_ok, module_ok, load_ok, fib_found,
                parse_result ? parse_result : "ok",
                load_result ? load_result : "ok",
                find_result ? find_result : "ok");
            fclose(out);
        } else {
            writeFailure();
        }
    }

    return 0;
}
