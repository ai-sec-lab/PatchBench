#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include <Magick++/Blob.h>
#include <Magick++/Image.h>

#include "utils.cc"

static void writeFailure()
{
  FILE *f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

#define FUZZ_ENCODER_STRING_LITERAL_X(name) FUZZ_ENCODER_STRING_LITERAL(name)
#define FUZZ_ENCODER_STRING_LITERAL(name) #name

#ifndef FUZZ_ENCODER
#define FUZZ_ENCODER FUZZ_ENCODER_STRING_LITERAL_X(FUZZ_IMAGEMAGICK_ENCODER)
#endif

#ifndef FUZZ_IMAGEMAGICK_INITIALIZER
#define FUZZ_IMAGEMAGICK_INITIALIZER ""
#endif
#define FUZZ_ENCODER_INITIALIZER FUZZ_ENCODER_STRING_LITERAL_X(FUZZ_IMAGEMAGICK_INITIALIZER)

static ssize_t EncoderInitializer(const uint8_t *Data, const size_t Size, Magick::Image &image)
{
  if (FUZZ_ENCODER_INITIALIZER == "interlace") {
    Magick::InterlaceType interlace = (Magick::InterlaceType) *reinterpret_cast<const char *>(Data);
    if (interlace > Magick::PNGInterlace)
      return -1;
    image.interlaceType(interlace);
    return 1;
  }

  return 0;
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size) {
  /* ImageMagick stamps the current wall-clock time into the encoded
     output (date:create / date:modify), which would make /tmp/output
     differ between runs of the same input. ImageMagick honors
     SOURCE_DATE_EPOCH for exactly these properties. */
  setenv("SOURCE_DATE_EPOCH", "0", 1);

  Magick::Image image;
  const ssize_t offset = EncoderInitializer(Data, Size, image);
  if (offset < 0) {
    writeFailure();
    return 0;
  }
  std::string encoder = FUZZ_ENCODER;
  image.magick(encoder);
  image.fileName(std::string(encoder) + ":");
  const Magick::Blob blob(Data + offset, Size - offset);
  try {
    image.read(blob);
  }
  catch (Magick::Exception &e) {
    writeFailure();
    return 0;
  }

  /* Record the decoded image before attempting the encode. image.write() can
     abort the process outright -- on this id it trips an ASAN double-free
     inside ImageToBlob() -- and an aborted run leaves no /tmp/output at all,
     not even the sentinel. Writing the decode result first guarantees a
     deterministic record survives; the encoded blob overwrites it below when
     the encode completes. */
  {
    std::string fmt;
    unsigned long columns = 0, rows = 0, depth = 0;
    int colorspace = 0;
    bool ok = false;
    try {
      fmt        = image.magick();
      columns    = (unsigned long) image.columns();
      rows       = (unsigned long) image.rows();
      depth      = (unsigned long) image.depth();
      colorspace = (int) image.colorSpace();
      ok = true;
    }
    catch (Magick::Exception &e) {
    }
    if (ok) {
      FILE *f = fopen("/tmp/output", "wb");
      if (f) {
        fprintf(f, "format=%s\n", fmt.c_str());
        fprintf(f, "columns=%lu\n", columns);
        fprintf(f, "rows=%lu\n", rows);
        fprintf(f, "depth=%lu\n", depth);
        fprintf(f, "colorspace=%d\n", colorspace);
        fclose(f);
      }
    } else {
      writeFailure();
    }
  }

#if FUZZ_IMAGEMAGICK_ENCODER_WRITE || BUILD_MAIN

  Magick::Blob outBlob;
  bool wrote = false;
  try {
    image.write(&outBlob, encoder);
    if (outBlob.data() && outBlob.length() > 0) {
      FILE *f = fopen("/tmp/output", "wb");
      if (f) {
        fwrite(outBlob.data(), 1, outBlob.length(), f);
        fclose(f);
        wrote = true;
      }
    }
  }
  catch (Magick::Exception &e) {
  }
  /* A failed encode leaves the decode record from above in place. */
  (void) wrote;
#else
  /* No write support for this encoder: the decode record written above
     is the whole output. */
#endif
  return 0;
}

#include "travis.cc"
