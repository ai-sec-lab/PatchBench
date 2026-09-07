/*
 * Copyright (c) 2020, the SerenityOS developers.
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include <LibGfx/Bitmap.h>
#include <LibGfx/ImageFormats/JPEGLoader.h>
#include <cstdio>
#include <stddef.h>
#include <stdint.h>

static void writeFailure(void)
{
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

extern "C" int LLVMFuzzerTestOneInput(uint8_t const* data, size_t size)
{
    auto decoder_or_error = Gfx::JPEGImageDecoderPlugin::create({ data, size });
    if (decoder_or_error.is_error()) {
        writeFailure();
        return 0;
    }
    auto decoder = decoder_or_error.release_value();
    decoder->initialize();

    auto frame_or_error = decoder->frame(0);
    if (frame_or_error.is_error()) {
        writeFailure();
        return 0;
    }

    auto frame = frame_or_error.release_value();
    if (!frame.image) {
        writeFailure();
        return 0;
    }

    auto& bmp = *frame.image;
    FILE *f = fopen("/tmp/output", "wb");
    if (!f) {
        writeFailure();
        return 0;
    }

    fprintf(f,
            "width=%d\n"
            "height=%d\n"
            "physical_width=%d\n"
            "physical_height=%d\n"
            "pitch=%zu\n"
            "format=%d\n"
            "size_in_bytes=%zu\n"
            "duration=%d\n"
            "--\n",
            bmp.width(), bmp.height(),
            bmp.physical_width(), bmp.physical_height(),
            bmp.pitch(),
            (int)bmp.format(),
            bmp.size_in_bytes(),
            frame.duration);

    if (bmp.physical_height() > 0) {
        u8 const* row0 = bmp.scanline_u8(0);
        size_t bytes = bmp.size_in_bytes();
        if (row0 && bytes > 0)
            fwrite(row0, 1, bytes, f);
    }

    fclose(f);
    return 0;
}
