/*
 * Copyright (c) 2021, Brian Gianforcaro <bgianf@serenityos.org>
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include <LibTLS/Certificate.h>
#include <cstdio>
#include <stddef.h>
#include <stdint.h>

static void writeFailure(void)
{
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

extern "C" int LLVMFuzzerTestOneInput(uint8_t const* data, size_t size)
{
    auto cert = TLS::Certificate::parse_asn1({ data, size });

    if (!cert.has_value()) {
        writeFailure();
        return 0;
    }

    auto const& c = cert.value();
    FILE *f = fopen("/tmp/output", "wb");
    if (!f) {
        writeFailure();
        return 0;
    }

    fprintf(f,
            "version=%u\n"
            "algorithm=%d\n"
            "key_algorithm=%d\n"
            "ec_algorithm=%d\n"
            "signature_algorithm=%d\n"
            "der_size=%zu\n"
            "data_size=%zu\n"
            "fingerprint_size=%zu\n"
            "signature_value_size=%zu\n"
            "original_asn1_size=%zu\n"
            "san_count=%zu\n"
            "is_self_issued=%d\n"
            "is_certificate_authority=%d\n"
            "is_allowed_to_sign_certificate=%d\n",
            (unsigned)c.version,
            (int)c.algorithm,
            (int)c.key_algorithm,
            (int)c.ec_algorithm,
            (int)c.signature_algorithm,
            c.der.size(),
            c.data.size(),
            c.fingerprint.size(),
            c.signature_value.size(),
            c.original_asn1.size(),
            c.SAN.size(),
            c.is_self_issued ? 1 : 0,
            c.is_certificate_authority ? 1 : 0,
            c.is_allowed_to_sign_certificate ? 1 : 0);
    fclose(f);
    return 0;
}
