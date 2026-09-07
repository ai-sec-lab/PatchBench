/*
 * Copyright 2019 Google, LLC
 *
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE file.
 */

#include "src/gpu/GrShaderCaps.h"
#include "src/sksl/SkSLCompiler.h"
#include "src/sksl/SkSLPipelineStageCodeGenerator.h"
#include "src/sksl/ir/SkSLVarDeclarations.h"
#include "src/sksl/ir/SkSLVariable.h"

#include "fuzz/Fuzz.h"

bool FuzzSKSL2Pipeline(sk_sp<SkData> bytes) {
    sk_sp<GrShaderCaps> caps = SkSL::ShaderCapsFactory::Default();
    SkSL::Compiler compiler(caps.get());
    SkSL::Program::Settings settings;
    std::unique_ptr<SkSL::Program> program = compiler.convertProgram(
                                                    SkSL::Program::kRuntimeEffect_Kind,
                                                    SkSL::String((const char*) bytes->data(),
                                                                 bytes->size()),
                                                    settings);
    if (!program) {
        return false;
    }

    class Callbacks : public SkSL::PipelineStage::Callbacks {
        using String = SkSL::String;

        String declareUniform(const SkSL::VarDeclaration* decl) override {
            return decl->var().name();
        }

        void defineFunction(const char* /*decl*/, const char* /*body*/, bool /*isMain*/) override {}
        void defineStruct(const char* /*definition*/) override {}

        String sampleChild(int index, String coords) override {
            return SkSL::String::printf("sample(%d%s%s)", index, coords.empty() ? "" : ", ",
                                        coords.c_str());
        }

        String sampleChildWithMatrix(int index, String matrix) override {
            return SkSL::String::printf("sample(%d%s%s)", index, matrix.empty() ? "" : ", ",
                                        matrix.c_str());
        }
    };

    Callbacks callbacks;
    SkSL::PipelineStage::ConvertProgram(*program, "coords", &callbacks);
    return true;
}

#if defined(SK_BUILD_FOR_LIBFUZZER)
#include <cstdio>

static void writeFailure() {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size > 3000) {
        writeFailure();
        return 0;
    }
    auto bytes = SkData::MakeWithoutCopy(data, size);
    bool result = FuzzSKSL2Pipeline(bytes);

    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fprintf(f, "size=%zu\nresult=%d\n", size, result ? 1 : 0);
        fclose(f);
    } else {
        writeFailure();
    }
    return 0;
}
#endif
