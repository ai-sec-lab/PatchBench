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

#include "decompressors/LJpegDecompressor.h" // for LJpegDecompressor
#include "common/RawImage.h"                 // for RawImage
#include "common/RawspeedException.h"        // for RawspeedException
#include "fuzz/Common.h"                     // for CreateRawImage
#include "io/Buffer.h"                       // for Buffer, DataBuffer
#include "io/ByteStream.h"                   // for ByteStream
#include "io/Endianness.h"                   // for Endianness, Endianne...
#include <cassert>                           // for assert
#include <cstdint>                           // for uint8_t
#include <cstdio>                            // for size_t

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* Data, size_t Size);

static void writeFailure() {
  FILE* f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* Data, size_t Size) {
  assert(Data);

  try {
    const rawspeed::Buffer b(Data, Size);
    const rawspeed::DataBuffer db(b, rawspeed::Endianness::little);
    rawspeed::ByteStream bs(db);

    rawspeed::RawImage mRaw(CreateRawImage(&bs));

    const auto offsetX = bs.getU32();
    const auto offsetY = bs.getU32();
    const auto fixDng16Bug = bs.getU32();

    rawspeed::LJpegDecompressor j(bs, mRaw);
    mRaw->createData();
    j.decode(offsetX, offsetY, fixDng16Bug);

    // we can not check that all the image was initialized, because normally
    // LJpegDecompressor decodes just some one tile/slice.
    if (mRaw->isAllocated() && mRaw->dim.y > 0 && mRaw->pitch > 0) {
      // Walk row-by-row using dim.x*bpp bytes per row, skipping the
      // per-row padding that ASan-enabled librawspeed leaves poisoned.
      const size_t row_bytes =
          static_cast<size_t>(mRaw->dim.x) * static_cast<size_t>(mRaw->getBpp());
      FILE* f = fopen("/tmp/output", "wb");
      if (f) {
        bool ok = true;
        for (int y = 0; y < mRaw->dim.y && ok; y++) {
          if (fwrite(mRaw->getData(0, y), 1, row_bytes, f) != row_bytes)
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
    // Exceptions are good, crashes are bad.
    writeFailure();
  }

  return 0;
}
