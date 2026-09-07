/*
---------------------------------------------------------------------------
Open Asset Import Library (assimp)
---------------------------------------------------------------------------

Copyright (c) 2006-2024, assimp team

All rights reserved.

Redistribution and use of this software in source and binary forms,
with or without modification, are permitted provided that the following
conditions are met:

* Redistributions of source code must retain the above
  copyright notice, this list of conditions and the
  following disclaimer.

* Redistributions in binary form must reproduce the above
  copyright notice, this list of conditions and the
  following disclaimer in the documentation and/or other
  materials provided with the distribution.

* Neither the name of the assimp team, nor the names of its
  contributors may be used to endorse or promote products
  derived from this software without specific prior
  written permission of the assimp team.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
---------------------------------------------------------------------------
*/
#include <assimp/cimport.h>
#include <assimp/Importer.hpp>
#include <assimp/Exporter.hpp>
#include <assimp/scene.h>
#include <assimp/postprocess.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <vector>

using namespace Assimp;

static void writeFailure() {
    FILE *output = fopen("/tmp/output", "wb");
    if (output) {
        fwrite("failed to save /tmp/output", 1, 26, output);
        fclose(output);
    }
}

// The FBX exporter writes the host's current wall-clock time into the
// FBXHeaderExtension/CreationTimeStamp node, which makes /tmp/output differ
// between runs of the same input. Blank those time fields so the saved output
// is deterministic. (FileId and the Document CreationTime string are hardcoded
// constants in Assimp, so only CreationTimeStamp needs handling.)
static void stripFbxTimestamp(std::vector<uint8_t> &fbx) {
    static const char *const kFields[] = {
        "Year", "Month", "Day", "Hour", "Minute", "Second", "Millisecond",
    };
    const char marker[] = "CreationTimeStamp";
    const size_t markerLen = sizeof(marker) - 1;
    const size_t n = fbx.size();
    uint8_t *data = fbx.data();

    size_t start = 0;
    bool found = false;
    for (size_t i = 0; i + markerLen <= n; ++i) {
        if (memcmp(data + i, marker, markerLen) == 0) {
            start = i + markerLen;
            found = true;
            break;
        }
    }
    if (!found) {
        return;
    }

    // Each leaf field is encoded as <NameLen:u8><Name><'I'><int32 value>.
    // Match the length-prefixed name to avoid spurious hits, then zero the
    // 4-byte value that follows the 'I' property-type code.
    for (const char *name : kFields) {
        const uint8_t nameLen = static_cast<uint8_t>(strlen(name));
        for (size_t i = start; i + 1 + nameLen + 1 + 4 <= n; ++i) {
            if (data[i] == nameLen &&
                memcmp(data + i + 1, name, nameLen) == 0 &&
                data[i + 1 + nameLen] == 'I') {
                memset(data + i + 1 + nameLen + 1, 0, 4);
                break;
            }
        }
    }
}

// Assimp writes its own version into the FBX "Creator" node, and the revision
// component is the build's git hash: CMake feeds `git rev-parse --short=8 HEAD`
// into GitVersion, which aiGetVersionRevision() returns. That makes /tmp/output
// depend on the image's commit rather than on the input, so rebuilding the
// image changes every exported file. Blank the version digits.
static void stripFbxCreatorVersion(std::vector<uint8_t> &fbx) {
    static const char prefix[] = "Open Asset Import Library (Assimp) ";
    const size_t prefixLen = sizeof(prefix) - 1;
    const size_t n = fbx.size();
    uint8_t *data = fbx.data();

    for (size_t i = 0; i + prefixLen <= n; ++i) {
        if (memcmp(data + i, prefix, prefixLen) != 0) {
            continue;
        }
        // Overwrite the version characters in place. The byte count is
        // unchanged, so the string length and every FBX offset stay valid.
        for (size_t j = i + prefixLen;
             j < n && ((data[j] >= '0' && data[j] <= '9') || data[j] == '.');
             ++j) {
            data[j] = '0';
        }
    }
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t dataSize) {
    aiLogStream stream = aiGetPredefinedLogStream(aiDefaultLogStream_STDOUT,NULL);
    aiAttachLogStream(&stream);

    Importer importer;
    const aiScene *sc = importer.ReadFileFromMemory(data, dataSize,
        aiProcessPreset_TargetRealtime_Quality, nullptr );

    if (sc == nullptr) {
        aiDetachLogStream(&stream);
        writeFailure();
        return 0;
    }

    Exporter exporter;
    const aiExportDataBlob *blob = exporter.ExportToBlob(sc, "fbx");

    if (blob && blob->data && blob->size > 0) {
        std::vector<uint8_t> fbx(
            static_cast<const uint8_t *>(blob->data),
            static_cast<const uint8_t *>(blob->data) + blob->size);
        stripFbxTimestamp(fbx);
        stripFbxCreatorVersion(fbx);
        FILE *output = fopen("/tmp/output", "wb");
        if (output) {
            size_t written = fwrite(fbx.data(), 1, fbx.size(), output);
            fclose(output);
            if (written != fbx.size()) {
                writeFailure();
            }
        } else {
            writeFailure();
        }
    } else {
        writeFailure();
    }

    aiDetachLogStream(&stream);

    return 0;
}

