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
#include <cstdlib>

#include <Magick++/Blob.h>
#include <Magick++/Image.h>

#include "utils.cc"
#include "encoder_utils.cc"

static bool validateFileName(const std::string &fileName)
{
  // Signature: this will most likely cause a timeout.
  if (fileName.find("%#") != -1)
    return(false);

  return(true);
}

static void writeFailure()
{
  FILE *f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *Data,size_t Size)
{
  /* ImageMagick stamps the current wall-clock time into the MIFF
     date:create / date:modify / date:timestamp properties, which makes
     /tmp/output differ between runs of the same input. Pin it to a fixed epoch
     so the encoded output is reproducible (ImageMagick honors
     SOURCE_DATE_EPOCH for these date properties). */
  setenv("SOURCE_DATE_EPOCH", "0", 1);

  if (IsInvalidSize(Size)) {
    writeFailure();
    return 0;
  }
  std::string fileName(reinterpret_cast<const char *>(Data), Size);
  if (!validateFileName(fileName)) {
    writeFailure();
    return 0;
  }
  try {
    Magick::Image image;
    image.read(std::string("label:") + fileName);

    Magick::Blob outBlob;
    image.write(&outBlob, "miff");
    if (outBlob.data() && outBlob.length() > 0) {
      FILE *f = fopen("/tmp/output", "wb");
      if (f) {
        fwrite(outBlob.data(), 1, outBlob.length(), f);
        fclose(f);
        return 0;
      }
    }
    writeFailure();
  }
  catch (Magick::Exception &e) {
    writeFailure();
  }
  return 0;
}
