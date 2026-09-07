#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mruby.h>
#include <mruby/compile.h>
#include <mruby/error.h>
#include <mruby/string.h>
#include <mruby/value.h>

static void writeFailure(void) {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

static mrb_value do_inspect(mrb_state *mrb, void *userdata) {
    return mrb_inspect(mrb, *(mrb_value *)userdata);
}

int LLVMFuzzerTestOneInput(uint8_t *Data, size_t size) {
    if (size < 1) {
        writeFailure();
        return 0;
    }
    char *code = malloc(size+1);
    memcpy(code, Data, size);
    code[size] = '\0';
    mrb_state *mrb = mrb_open();
    mrb_value result = mrb_load_string(mrb, code);

    mrb_value to_inspect = mrb->exc ? mrb_obj_value(mrb->exc) : result;
    mrb_bool err = 0;
    mrb_value str = mrb_protect_error(mrb, do_inspect, &to_inspect, &err);

    FILE *out = fopen("/tmp/output", "wb");
    if (out) {
        fprintf(out, "%s: ", mrb->exc ? "exception" : "result");
        if (!err && mrb_string_p(str)) {
            fwrite(RSTRING_PTR(str), 1, RSTRING_LEN(str), out);
        } else {
            fwrite("(inspect failed)", 1, 16, out);
        }
        fputc('\n', out);
        fclose(out);
    } else {
        writeFailure();
    }

    mrb_close(mrb);
    free(code);
    return 0;
}
