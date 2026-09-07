#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
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
  if (FUZZ_ENCODER_INITIALIZER == "interlace") {
    Magick::InterlaceType interlace = (Magick::InterlaceType) *reinterpret_cast<const char *>(Data);
    if (interlace > Magick::PNGInterlace)
      return -1;
    image.interlaceType(interlace);
    return 1;
  }

  return 0;
}

/* --- PostScript header fallback --------------------------------------
   ImageMagick's PS/EPS coder has no header-only path: ReadPSImage() scans
   the DSC comments (ReadPSInfo) and then unconditionally hands rendering
   to the Ghostscript delegate.  With no `gs` on PATH the delegate fails,
   the partially-populated image is destroyed, and ping() surfaces only
   "No image was loaded" -- so nothing the coder parsed ever reaches us.

   To keep this id producing a deterministic record, re-scan the same DSC
   comments ReadPSInfo looks for and log what they say.  This is the
   harness's OWN parse and does not run through the coder, so the record
   is marked stage=dsc(harness) to keep that unambiguous.
   ------------------------------------------------------------------ */

static const char *findToken(const char *data, const size_t size,
  const char *token)
{
  size_t length = strlen(token);
  if (size < length)
    return (const char *) NULL;
  for (size_t i = 0; i + length <= size; i++)
    if (memcmp(data + i, token, length) == 0)
      return data + i;
  return (const char *) NULL;
}

static size_t countToken(const char *data, const size_t size,
  const char *token)
{
  size_t length = strlen(token), n = 0;
  if (size < length)
    return 0;
  for (size_t i = 0; i + length <= size; i++)
    if (memcmp(data + i, token, length) == 0)
      n++;
  return n;
}

/* Read the four numbers following a DSC bounding-box comment.  The slice
   is copied into a bounded buffer first so sscanf cannot run off the end
   of the (not NUL-terminated) blob. */
static bool readBounds(const char *data, const size_t size,
  const char *token, double bounds[4])
{
  const char *p = findToken(data, size, token);
  if (p == (const char *) NULL)
    return false;
  char line[256];
  size_t available = size - (size_t) (p - data);
  size_t n = available < sizeof(line) - 1 ? available : sizeof(line) - 1;
  memcpy(line, p, n);
  line[n] = '\0';
  return sscanf(line + strlen(token), " %lf %lf %lf %lf", &bounds[0],
    &bounds[1], &bounds[2], &bounds[3]) == 4;
}

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

static void printBounds(FILE *f, const char *name, const bool found,
  const double bounds[4])
{
  if (found == false)
    {
      fprintf(f, "%s=none\n", name);
      return;
    }
  fprintf(f, "%s=%.10g %.10g %.10g %.10g\n", name, bounds[0], bounds[1],
    bounds[2], bounds[3]);
}

static bool writeDscReport(const uint8_t *Data, const size_t Size,
  const std::string &encoder, const std::string &why)
{
  const char *data = (const char *) Data;
  bool signature = (Size >= 2) && (data[0] == '%') && (data[1] == '!');
  double boundingBox[4], hiResBoundingBox[4], pageBoundingBox[4];
  bool haveBoundingBox = readBounds(data, Size, "%%BoundingBox:", boundingBox);
  bool haveHiRes = readBounds(data, Size, "%%HiResBoundingBox:",
    hiResBoundingBox);
  bool havePage = readBounds(data, Size, "%%PageBoundingBox:",
    pageBoundingBox);
  const char *imageData = findToken(data, Size, "%ImageData:");

  /* Nothing PostScript-shaped in here: leave the sentinel, the same way
     an unparseable input would be reported for any other coder. */
  if ((signature == false) && (haveBoundingBox == false) &&
      (haveHiRes == false) && (havePage == false) &&
      (imageData == (const char *) NULL))
    return false;

  FILE *f = fopen("/tmp/output", "wb");
  if (f == NULL)
    return false;
  fprintf(f, "stage=dsc(harness)\n");
  fprintf(f, "encoder=%s\n", encoder.c_str());
  fprintf(f, "size=%lu\n", (unsigned long) Size);
  fprintf(f, "signature=%d\n", signature ? 1 : 0);
  printBounds(f, "BoundingBox", haveBoundingBox, boundingBox);
  printBounds(f, "HiResBoundingBox", haveHiRes, hiResBoundingBox);
  printBounds(f, "PageBoundingBox", havePage, pageBoundingBox);
  fprintf(f, "ImageData=%d\n", imageData != (const char *) NULL ? 1 : 0);
  fprintf(f, "documents=%lu\n",
    (unsigned long) countToken(data, Size, "%%BeginDocument"));
  fprintf(f, "coder_error=%s\n", tidyError(why).c_str());
  fclose(f);
  return true;
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size) {
  /* ImageMagick stamps wall-clock time into image properties; pin it so
     repeated runs of the same input agree. */
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
    image.ping(blob);
  }
  catch (Magick::Exception &e) {
    if (!writeDscReport(Data + offset, Size - offset, encoder, e.what()))
      writeFailure();
    return 0;
  }

  /* ping() decodes the header only -- there is no output blob to save, so
     report what it managed to parse. Read every field first: a throw
     part-way through must not leave a half-written /tmp/output. */
  std::string format;
  unsigned long columns = 0, rows = 0, depth = 0;
  int colorspace = 0;
  bool ok = false;
  try {
    format     = image.magick();
    columns    = (unsigned long) image.columns();
    rows       = (unsigned long) image.rows();
    depth      = (unsigned long) image.depth();
    colorspace = (int) image.colorSpace();
    ok = true;
  }
  catch (Magick::Exception &e) {
  }

  bool wrote = false;
  if (ok) {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
      fprintf(f, "format=%s\n", format.c_str());
      fprintf(f, "columns=%lu\n", columns);
      fprintf(f, "rows=%lu\n", rows);
      fprintf(f, "depth=%lu\n", depth);
      fprintf(f, "colorspace=%d\n", colorspace);
      fclose(f);
      wrote = true;
    }
  }
  if (!wrote) writeFailure();
  return 0;
}

#include "travis.cc"
