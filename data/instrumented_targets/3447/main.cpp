/*
    RawSpeed - RAW file decoder.

    Copyright (C) 2017 Roman Lebedev

    This library is free software; you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public
    License as published by the Free Software Foundation; either
    version 2 of the License, or (at your option) any later version.

    This library is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
    Lesser General Public License for more details.

    You should have received a copy of the GNU Lesser General Public
    License along with this library; if not, write to the Free Software
    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
*/

#ifndef DECODER
#error DECODER must be defined
#endif

#include "common/RawspeedException.h" // for RawspeedException
#include "decoders/ArwDecoder.h"      // IWYU pragma: keep
#include "decoders/Cr2Decoder.h"      // IWYU pragma: keep
#include "decoders/DcrDecoder.h"      // IWYU pragma: keep
#include "decoders/DcsDecoder.h"      // IWYU pragma: keep
#include "decoders/DngDecoder.h"      // IWYU pragma: keep
#include "decoders/ErfDecoder.h"      // IWYU pragma: keep
#include "decoders/IiqDecoder.h"      // IWYU pragma: keep
#include "decoders/KdcDecoder.h"      // IWYU pragma: keep
#include "decoders/MefDecoder.h"      // IWYU pragma: keep
#include "decoders/MosDecoder.h"      // IWYU pragma: keep
#include "decoders/NefDecoder.h"      // IWYU pragma: keep
#include "decoders/OrfDecoder.h"      // IWYU pragma: keep
#include "decoders/PefDecoder.h"      // IWYU pragma: keep
#include "decoders/RafDecoder.h"      // IWYU pragma: keep
#include "decoders/Rw2Decoder.h"      // IWYU pragma: keep
#include "decoders/SrwDecoder.h"      // IWYU pragma: keep
#include "decoders/ThreefrDecoder.h"  // IWYU pragma: keep
#include "io/Buffer.h"                // for Buffer, DataBuffer
#include "metadata/CameraMetaData.h"  // for CameraMetaData
#include "parsers/TiffParser.h"       // for TiffParser
#include <algorithm>                  // for move
#include <cassert>                    // for assert
#include <cstdint>                    // for uint8_t
#include <cstdio>                     // for size_t
#include <memory>                     // for unique_ptr

// define this function, it is only declared in rawspeed:
// for fuzzing, do not want any threading.
extern "C" int __attribute__((const)) rawspeed_get_number_of_processor_cores() {
  return 1;
}

static const rawspeed::CameraMetaData metadata{};

static void writeFailure() {
  FILE* f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* Data, size_t Size);

using rawspeed::DECODER;

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* Data, size_t Size) {
  assert(Data);

  try {
    const rawspeed::Buffer buffer(Data, Size);
    auto ifd = rawspeed::TiffParser::parse(buffer);

    // ATM do not care if this is the appropriate decoder.
    // only check that the check does not crash.
    (void)DECODER::isAppropriateDecoder(ifd.get(), &buffer);

    auto decoder = std::make_unique<DECODER>(std::move(ifd), &buffer);

    decoder->applyCrop = false;
    decoder->failOnUnknown = false;
    // decoder->checkSupport(&metadata);

    decoder->decodeRaw();
    decoder->decodeMetaData(&metadata);

    if (decoder->mRaw->isAllocated() &&
        decoder->mRaw->dim.y > 0 && decoder->mRaw->pitch > 0) {
      // Walk row-by-row using dim.x*bpp bytes per row, skipping the
      // per-row padding that ASan-enabled librawspeed leaves poisoned.
      const size_t row_bytes =
          static_cast<size_t>(decoder->mRaw->dim.x) *
          static_cast<size_t>(decoder->mRaw->getBpp());
      FILE* f = fopen("/tmp/output", "wb");
      if (f) {
        bool ok = true;
        for (int y = 0; y < decoder->mRaw->dim.y && ok; y++) {
          if (fwrite(decoder->mRaw->getData(0, y), 1, row_bytes, f) != row_bytes)
            ok = false;
        }
        fclose(f);
        if (!ok) writeFailure();
      } else {
        writeFailure();
      }
    } else {
      writeFailure();
    }

  } catch (rawspeed::RawspeedException&) {
    writeFailure();
    return 0;
  }

  return 0;
}
