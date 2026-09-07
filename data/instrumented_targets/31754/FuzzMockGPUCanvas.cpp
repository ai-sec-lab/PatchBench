/*
 * Copyright 2018 Google, LLC
 *
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 */

#include "fuzz/Fuzz.h"
#include "src/core/SkFontMgrPriv.h"
#include "tools/fonts/TestFontMgr.h"

#include <cstdio>

static void writeFailure() {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

void fuzz_MockGPUCanvas(Fuzz* f);

extern "C" {

    // Set default LSAN options.
    const char *__lsan_default_options() {
        // Don't print the list of LSAN suppressions on every execution.
        return "print_suppressions=0";
    }

    int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
        if (size > 4000) {
            writeFailure();
            return 0;
        }
        gSkFontMgr_DefaultFactory = &ToolUtils::MakePortableFontMgr;
        auto fuzz = Fuzz(SkData::MakeWithoutCopy(data, size));
        fuzz_MockGPUCanvas(&fuzz);

        FILE *f = fopen("/tmp/output", "wb");
        if (f) {
            fprintf(f, "size=%zu\ncompleted=1\n", size);
            fclose(f);
        } else {
            writeFailure();
        }
        return 0;
    }
}  // extern "C"
