#include <stdio.h>
#include <unistd.h>

#include <gpac/filters.h>
#include <gpac/constants.h>

static void writeFailure(void)
{
    FILE *output = fopen("/tmp/output", "wb");
    if (output) {
        fwrite("failed to save /tmp/output", 1, 26, output);
        fclose(output);
    }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    /* A fixed name, not "/tmp/libfuzzer.%d" with getpid(): the inspect filter
       echoes this path back as name=/SourcePath=/URL=/Extension= in its XML,
       so a pid in the name makes /tmp/output differ between runs of the same
       input. Runs are sequential within a container, so a constant is safe. */
    static const char filename[] = "/tmp/libfuzzer.0";
    GF_Err e;

    /* Sentinel first: even if anything below aborts, /tmp/output exists. */
    writeFailure();

    FILE *fp = fopen(filename, "wb");
    if (!fp) return 0;
    fwrite(data, size, 1, fp);
    fclose(fp);

    /* The inspect filter writes its analysis to its `log` target, which
       defaults to stdout. Rather than passing `log=/tmp/output` through the
       fragile filter-URL parser, redirect stdout to /tmp/output for the
       duration of the run, then restore it. */
    fflush(stdout);
    int saved_stdout = dup(fileno(stdout));
    FILE *redirected = freopen("/tmp/output", "w", stdout);

    GF_FilterSession *fs = gf_fs_new_defaults(0);
    if (fs) {
        GF_Filter *src = gf_fs_load_source(fs, filename, NULL, NULL, &e);
        GF_Filter *insp = gf_fs_load_filter(fs, "inspect:deep:analyze=bs", &e);
        if (src && insp)
            gf_fs_run(fs);
        gf_fs_del(fs);
    }

    fflush(stdout);
    if (saved_stdout >= 0) {
        dup2(saved_stdout, fileno(stdout));
        close(saved_stdout);
        clearerr(stdout);
    }

    /* If the redirection failed outright, fall back to the sentinel. */
    if (!redirected)
        writeFailure();

    unlink(filename);
    return 0;
}
