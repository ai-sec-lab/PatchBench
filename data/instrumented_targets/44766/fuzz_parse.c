#include <stdio.h>
#include <unistd.h>

#include <gpac/internal/isomedia_dev.h>
#include <gpac/constants.h>

static void writeFailure(void) {
    FILE *output = fopen("/tmp/output", "wb");
    if (output) {
        fwrite("failed to save /tmp/output", 1, 26, output);
        fclose(output);
    }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    /* A fixed name, not "/tmp/libfuzzer.%d" with getpid(): gf_isom dumps this
       path back into the XML as Name="libfuzzer.<pid>", so a pid in the name
       makes /tmp/output differ between runs of the same input. Runs are
       sequential within a container, so a constant is safe. */
    static const char filename[] = "/tmp/libfuzzer.0";

    FILE *fp = fopen(filename, "wb");
    if (!fp) {
        writeFailure();
        return 0;
    }
    fwrite(data, size, 1, fp);
    fclose(fp);

    GF_ISOFile *movie = NULL;
    movie = gf_isom_open_file(filename, GF_ISOM_OPEN_READ_DUMP, NULL);
    if (movie != NULL) {
        FILE *output = fopen("/tmp/output", "wb");
        if (output) {
            if (gf_isom_dump(movie, output, GF_FALSE, GF_FALSE) != GF_OK) {
                fclose(output);
                writeFailure();
            } else {
                fclose(output);
            }
        } else {
            writeFailure();
        }
        gf_isom_close(movie);
    } else {
        writeFailure();
    }
    unlink(filename);
    return 0;
}
