#include <string>
#include <iostream>
#include <fstream>
#include <cstdio>

#include <mruby.h>
#include <mruby/class.h>
#include <mruby/compile.h>

#include <src/libfuzzer/libfuzzer_macro.h>
#include <ruby.pb.h>
#include "proto_to_ruby.h"

using namespace ruby_fuzzer;
using namespace std;

static void writeFailure(void) {
  FILE *f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

int FuzzRB(const uint8_t *Data, size_t size) {
  mrb_value v;
  (void)v;

  /* Sentinel first so /tmp/output always exists. */
  writeFailure();

  mrb_state *mrb = mrb_open();
  if (!mrb)
    return 0;

  char *code = (char *)malloc(size+1);
  if (!code) {
    mrb_close(mrb);
    return 0;
  }
  memcpy(code, Data, size);
  code[size] = '\0';

  if (const char *dump_path = getenv("PROTO_FUZZER_DUMP_PATH")) {
    // With libFuzzer binary run this to generate an RB file x.rb:
    // PROTO_FUZZER_DUMP_PATH=x.rb ./a.out proto-input
    std::ofstream of(dump_path);
    of.write(code, size);
  }
  std::cout << "\n\n############\n" << code << "\n############\n\n";
  v = mrb_load_string(mrb, code);

  {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
      fwrite(code, 1, size, f);
      fputs("\n--\n", f);
      if (mrb->exc) {
        struct RClass *cls = mrb_obj_class(mrb, mrb_obj_value(mrb->exc));
        const char *cname = cls ? mrb_class_name(mrb, cls) : "?";
        fprintf(f, "exception=%s\n", cname ? cname : "?");
      } else {
        fputs("no_exception\n", f);
      }
      fclose(f);
    } else {
      writeFailure();
    }
  }

  mrb_close(mrb);

  free(code);
  return 0;
}

DEFINE_PROTO_FUZZER(const Function &function) {
  protoConverter converter;
  auto s = converter.FunctionToString(function);
  (void)FuzzRB((const uint8_t*)s.data(), s.size());
}
