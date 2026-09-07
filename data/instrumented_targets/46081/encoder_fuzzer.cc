/*
  Copyright @ 2018 ImageMagick Studio LLC, a non-profit organization
  dedicated to making software imaging solutions freely available.
  
  You may not use this file except in compliance with the License.  You may
  obtain a copy of the License at
  
    https://imagemagick.org/script/license.php
  
  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
*/

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>

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
  if (strcmp(FUZZ_ENCODER_INITIALIZER, "interlace") == 0) {
    Magick::InterlaceType interlace = (Magick::InterlaceType) *reinterpret_cast<const char *>(Data);
    if (interlace > Magick::PNGInterlace)
      return -1;
    image.interlaceType(interlace);
    return 1;
  }
  if (strcmp(FUZZ_ENCODER_INITIALIZER, "png") == 0) {
    image.defineValue("png", "ignore-crc", "1");
  }

  return 0;
}

/* --- header fallback -------------------------------------------------
   The full encode path (read + write) stays the primary output.  When it
   throws we still record what ImageMagick itself managed to parse out of
   the header, rather than emitting only the failure sentinel.

   Pinging with subRange(1) sets image_info->number_scenes, and coders
   test (ping != MagickFalse) && (number_scenes != 0) to stop right after
   the header block -- before SetImageExtent() and before any quantum /
   pixel-cache allocation.  So these values come from the coder's own
   header parse and need nothing downstream of it to work.

   Note this reports the header only; it does not exercise the pixel
   pipeline, so the record is marked stage=header to keep that explicit.
   ------------------------------------------------------------------ */

/* ImageMagick error text is "<program>: <reason> `<description>' @ <site>".
   Only the reason is stable across runs -- the description can carry a
   per-run temporary filename -- so keep that and drop the rest. */
static std::string tidyError(const std::string &text)
{
  std::string out(text);
  size_t at = out.find(" @ ");
  if (at != std::string::npos)
    out.erase(at);
  size_t quote = out.find('`');
  if (quote != std::string::npos)
    out.erase(quote);
  size_t prefix = out.find(": ");
  if (prefix != std::string::npos)
    out.erase(0, prefix + 2);
  for (size_t i = 0; i < out.size(); i++)
    if (out[i] == '\n' || out[i] == '\r')
      out[i] = ' ';
  while (!out.empty() && out[out.size() - 1] == ' ')
    out.erase(out.size() - 1);
  return out;
}

static bool writeHeaderReport(const uint8_t *Data, const size_t Size,
  const std::string &encoder, const std::string &why)
{
  Magick::Image probe;
  probe.magick(encoder);
  probe.fileName(encoder + ":");
  probe.subImage(0);
  probe.subRange(1);

  std::string format;
  unsigned long columns = 0, rows = 0, depth = 0;
  int colorspace = 0, storageClass = 0, compression = 0;
  try {
    const Magick::Blob blob(Data, Size);
    probe.ping(blob);
    format       = probe.magick();
    columns      = (unsigned long) probe.columns();
    rows         = (unsigned long) probe.rows();
    depth        = (unsigned long) probe.depth();
    colorspace   = (int) probe.colorSpace();
    storageClass = (int) probe.classType();
    compression  = (int) probe.compressType();
  }
  catch (Magick::Exception &) {
    return false;
  }

  FILE *f = fopen("/tmp/output", "wb");
  if (f == NULL)
    return false;
  fprintf(f, "stage=header\n");
  fprintf(f, "format=%s\n", format.c_str());
  fprintf(f, "columns=%lu\n", columns);
  fprintf(f, "rows=%lu\n", rows);
  fprintf(f, "depth=%lu\n", depth);
  fprintf(f, "colorspace=%d\n", colorspace);
  fprintf(f, "class=%d\n", storageClass);
  fprintf(f, "compression=%d\n", compression);
  fprintf(f, "encoder_error=%s\n", tidyError(why).c_str());
  fclose(f);
  return true;
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size)
{
  /* ImageMagick stamps the current wall-clock time into the MIFF
     date:create / date:modify properties, which makes /tmp/output differ
     between runs of the same input. Pin it to a fixed epoch so the encoded
     output is reproducible (ImageMagick honors SOURCE_DATE_EPOCH for exactly
     these properties). */
  setenv("SOURCE_DATE_EPOCH", "0", 1);

  if (Size < 1) {
    writeFailure();
    return 0;
  }
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
    if (!writeHeaderReport(Data + offset, Size - offset, encoder, e.what()))
      writeFailure();
    return 0;
  }

#if FUZZ_IMAGEMAGICK_ENCODER_WRITE || BUILD_MAIN

  Magick::Blob outBlob;
  bool wrote = false;
  std::string writeError;
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
    writeError = e.what();
  }
  if (!wrote && !writeHeaderReport(Data + offset, Size - offset, encoder, writeError))
    writeFailure();
#else
  writeFailure();
#endif
  return 0;
}
