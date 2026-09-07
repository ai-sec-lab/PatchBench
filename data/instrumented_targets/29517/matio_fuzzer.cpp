// Copyright 2019 Google Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Adapter utility from fuzzer input to a temporary file, for fuzzing APIs that
// require a file instead of an input buffer.

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "fuzzer_temp_file.h"
#include "matio.h"

static void writeFailure() {
  FILE* f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  FuzzerTemporaryFile temp_file(data, size);

  mat_t* matfd = Mat_Open(temp_file.filename(), MAT_ACC_RDONLY);
  if (matfd == nullptr) {
    writeFailure();
    return 0;
  }

  FILE* out = fopen("/tmp/output", "wb");
  if (!out) {
    writeFailure();
    Mat_Close(matfd);
    return 0;
  }

  size_t n = 0;
  Mat_GetDir(matfd, &n);
  Mat_Rewind(matfd);

  fprintf(out, "n_vars=%zu\n", n);

  matvar_t* matvar = nullptr;
  unsigned idx = 0;
  while ((matvar = Mat_VarReadNextInfo(matfd)) != nullptr) {
    Mat_VarReadDataAll(matfd, matvar);
    size_t var_size = Mat_VarGetSize(matvar);
    fprintf(out, "var[%u]: name=%s class=%d data_type=%d rank=%d nbytes=%zu size=%zu",
            idx,
            matvar->name ? matvar->name : "(null)",
            (int)matvar->class_type,
            (int)matvar->data_type,
            matvar->rank,
            matvar->nbytes,
            var_size);
    if (matvar->dims && matvar->rank > 0) {
      fprintf(out, " dims=");
      for (int d = 0; d < matvar->rank; d++) {
        fprintf(out, "%s%zu", d ? "x" : "", matvar->dims[d]);
      }
    }
    fprintf(out, "\n");
    Mat_VarFree(matvar);
    idx++;
  }

  fclose(out);
  Mat_Close(matfd);

  return 0;
}
