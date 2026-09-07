#include "ndpi_api.h"
#include "fuzz_common_code.h"

#include <stdint.h>
#include <stdio.h>

struct ndpi_detection_module_struct *ndpi_info_mod = NULL;
struct ndpi_flow_struct ndpi_flow;
static ndpi_serializer json_serializer = {};
static ndpi_serializer csv_serializer = {};

static void writeFailure(void) {
  FILE *f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size) {
  if (ndpi_info_mod == NULL) {
    fuzz_init_detection_module(&ndpi_info_mod, NULL);

    ndpi_init_serializer(&json_serializer, ndpi_serialization_format_json);
    ndpi_init_serializer(&csv_serializer, ndpi_serialization_format_csv);
  }

  memset(&ndpi_flow, 0, SIZEOF_FLOW_STRUCT);
  ndpi_protocol detected_protocol =
    ndpi_detection_process_packet(ndpi_info_mod, &ndpi_flow, Data, Size, 0, NULL);
  detected_protocol = ndpi_detection_giveup(ndpi_info_mod, &ndpi_flow);

  ndpi_reset_serializer(&json_serializer);
  ndpi_reset_serializer(&csv_serializer);
  ndpi_dpi2json(ndpi_info_mod, &ndpi_flow, detected_protocol, &json_serializer);
  ndpi_dpi2json(ndpi_info_mod, &ndpi_flow, detected_protocol, &csv_serializer);

  {
    u_int32_t blen = 0;
    char *buf = ndpi_serializer_get_buffer(&json_serializer, &blen);
    if (buf && blen > 0) {
      FILE *out = fopen("/tmp/output", "wb");
      if (out) {
        fwrite(buf, 1, blen, out);
        fclose(out);
      } else {
        writeFailure();
      }
    } else {
      writeFailure();
    }
  }

  ndpi_free_flow_data(&ndpi_flow);

  return 0;
}
