#include "hb-fuzzer.hh"

#include <hb-ot.h>
#include <stdio.h>
#include <string.h>

#include <stdlib.h>

#define TEST_OT_FACE_NO_MAIN 1
#include "../api/test-ot-face.c"
#undef TEST_OT_FACE_NO_MAIN

static FILE *g_output = NULL;

static void writeFailure(void)
{
  FILE *output = fopen("/tmp/output", "wb");
  if (output) {
    fwrite("failed to save /tmp/output", 1, 26, output);
    fclose(output);
  }
}

static void dump_shaped_buffer(const char *tag, hb_buffer_t *buffer)
{
  if (!g_output) return;
  unsigned count = 0;
  hb_glyph_info_t *infos = hb_buffer_get_glyph_infos(buffer, &count);
  hb_glyph_position_t *positions = hb_buffer_get_glyph_positions(buffer, &count);
  fprintf(g_output, "shape %s: %u glyphs\n", tag, count);
  for (unsigned i = 0; i < count; i++) {
    fprintf(g_output, "  [%u] cp=%u cluster=%u xa=%d ya=%d xo=%d yo=%d\n",
            i, infos[i].codepoint, infos[i].cluster,
            positions[i].x_advance, positions[i].y_advance,
            positions[i].x_offset,  positions[i].y_offset);
  }
}

extern "C" int LLVMFuzzerTestOneInput (const uint8_t *data, size_t size)
{
  alloc_state = _fuzzing_alloc_state (data, size);

  g_output = fopen("/tmp/output", "wb");
  if (!g_output) writeFailure();

  hb_blob_t *blob = hb_blob_create ((const char *)data, size,
				    HB_MEMORY_MODE_READONLY, nullptr, nullptr);
  hb_face_t *face = hb_face_create (blob, 0);
  hb_font_t *font = hb_font_create (face);
  hb_ot_font_set_funcs (font);
  hb_font_set_scale (font, 12, 12);

  unsigned num_coords = 0;
  if (size) num_coords = data[size - 1];
  num_coords = hb_ot_var_get_axis_count (face) > num_coords ? num_coords : hb_ot_var_get_axis_count (face);
  int *coords = (int *) calloc (num_coords, sizeof (int));
  if (size > num_coords + 1)
    for (unsigned i = 0; i < num_coords; ++i)
      coords[i] = ((int) data[size - num_coords + i - 1] - 128) * 10;
  hb_font_set_var_coords_normalized (font, coords, num_coords);
  free (coords);

  {
    const char text[] = "ABCDEXYZ123@_%&)*$!";
    hb_buffer_t *buffer = hb_buffer_create ();
    hb_buffer_set_flags (buffer, (hb_buffer_flags_t) (HB_BUFFER_FLAG_VERIFY /* | HB_BUFFER_FLAG_PRODUCE_UNSAFE_TO_CONCAT */));
    hb_buffer_add_utf8 (buffer, text, -1, 0, -1);
    hb_buffer_guess_segment_properties (buffer);
    hb_shape (font, buffer, nullptr, 0);
    dump_shaped_buffer("utf8", buffer);
    hb_buffer_destroy (buffer);
  }

  uint32_t text32[16] = {0};
  unsigned int len = sizeof (text32);
  if (size < len)
    len = size;
  if (len)
    memcpy (text32, data + size - len, len);

  /* Misc calls on font. */
  text32[10] = test_font (font, text32[15]) % 256;

  hb_buffer_t *buffer = hb_buffer_create ();
 // hb_buffer_set_flags (buffer, (hb_buffer_flags_t) (HB_BUFFER_FLAG_VERIFY | HB_BUFFER_FLAG_PRODUCE_UNSAFE_TO_CONCAT));
  hb_buffer_add_utf32 (buffer, text32, sizeof (text32) / sizeof (text32[0]), 0, -1);
  hb_buffer_guess_segment_properties (buffer);
  hb_shape (font, buffer, nullptr, 0);
  dump_shaped_buffer("utf32", buffer);
  hb_buffer_destroy (buffer);

  hb_font_destroy (font);
  hb_face_destroy (face);
  hb_blob_destroy (blob);

  if (g_output) {
    fclose(g_output);
    g_output = NULL;
  }
  return 0;
}
