/*
 * Copyright (C) 2019 Frank Morgner <frankmorgner@gmail.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <stdio.h>

#include "fuzzer_reader.h"
#include "libopensc/pkcs15.h"
#include "libopensc/internal.h"

static void writeFailure(void) {
	FILE *f = fopen("/tmp/output", "wb");
	if (f) {
		fwrite("failed to save /tmp/output", 1, 26, f);
		fclose(f);
	}
}

uint16_t fuzz_get_buffer(const uint8_t **buf, size_t buf_len, const uint8_t **out, size_t *out_len)
{
	uint16_t len = 0;

	if (!buf || !(*buf) || buf_len < 2)
		return 0;

	/* Get length of the result buffer*/
	len = *((uint16_t *) *buf);
	if (buf_len - 2 <= len)
		return 0;
	(*buf) += 2;
	buf_len -= 2;
	
	/* Set out buffer to new reader data*/
	*out = *buf + len;
	*out_len = buf_len - len;
	return len;
}

int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size)
{
	size_t i = 0;
	struct sc_reader *reader = NULL;
	const uint8_t *buf = Data, *reader_data = NULL;
	uint16_t buf_len = 0;
	size_t reader_data_len = 0;
	struct sc_context *ctx = NULL;
	struct sc_pkcs15_card *p15card = NULL;
	sc_card_t *card = NULL;
	struct sc_pkcs15_tokeninfo *tokeninfo = NULL;
	int (* decode_entries[])(struct sc_pkcs15_card *, struct sc_pkcs15_object *,
			const u8 **nbuf, size_t *nbufsize) = {
		sc_pkcs15_decode_prkdf_entry, sc_pkcs15_decode_pukdf_entry,
		sc_pkcs15_decode_skdf_entry, sc_pkcs15_decode_cdf_entry,
		sc_pkcs15_decode_dodf_entry, sc_pkcs15_decode_aodf_entry
	};
	int algorithms[] = { SC_ALGORITHM_RSA, SC_ALGORITHM_EC, SC_ALGORITHM_GOSTR3410, SC_ALGORITHM_EDDSA };

	int stage_ctx_ok = 0;
	int stage_card_ok = 0;
	int stage_p15_ok = 0;
	unsigned decode_entry_successes[6] = {0};
	unsigned pubkey_decode_successes = 0;
	unsigned tokeninfo_version = 0;
	unsigned tokeninfo_flags = 0;
	size_t tokeninfo_label_len = 0;
	size_t tokeninfo_serial_len = 0;
	size_t tokeninfo_mfg_len = 0;

	/* Split data into testing buffer and APDU for connecting */
	if ((buf_len = fuzz_get_buffer(&buf, Size, &reader_data, &reader_data_len)) == 0) {
		writeFailure();
		return 0;
	}

	/* Establish context for fuzz app*/
	sc_establish_context(&ctx, "fuzz");
	if (!ctx) {
		writeFailure();
		return 0;
	}
	stage_ctx_ok = 1;

	if (fuzz_connect_card(ctx, &card, &reader, reader_data, reader_data_len) != SC_SUCCESS)
		goto err;
	stage_card_ok = 1;

	sc_pkcs15_bind(card, NULL, &p15card);
	if (!p15card)
		goto err;
	stage_p15_ok = 1;

	for (i = 0; i < sizeof decode_entries/sizeof *decode_entries; i++) {
		struct sc_pkcs15_object *obj;
		const u8 *p = buf;
		size_t len = (size_t) buf_len;
		if (!(obj = calloc(1, sizeof *obj)))
			goto err;
		while (SC_SUCCESS == decode_entries[i](p15card, obj, &p, &len)) {
			decode_entry_successes[i]++;
			sc_pkcs15_free_object(obj);
			if (!(obj = calloc(1, sizeof *obj)))
				goto err;
		}
		sc_pkcs15_free_object(obj);
	}

	for (i = 0; i < 4; i++) {
		struct sc_pkcs15_pubkey *pubkey = calloc(1, sizeof *pubkey);
		if (!pubkey)
			goto err;
		pubkey->algorithm = algorithms[i];
		if (sc_pkcs15_decode_pubkey(ctx, pubkey, buf, buf_len) == SC_SUCCESS)
			pubkey_decode_successes++;
		sc_pkcs15_free_pubkey(pubkey);
	}

	tokeninfo = sc_pkcs15_tokeninfo_new();
	if (tokeninfo) {
		sc_pkcs15_parse_tokeninfo(ctx, tokeninfo, buf, buf_len);
		tokeninfo_version = tokeninfo->version;
		tokeninfo_flags = tokeninfo->flags;
		tokeninfo_label_len = tokeninfo->label ? strlen(tokeninfo->label) : 0;
		tokeninfo_serial_len = tokeninfo->serial_number ? strlen(tokeninfo->serial_number) : 0;
		tokeninfo_mfg_len = tokeninfo->manufacturer_id ? strlen(tokeninfo->manufacturer_id) : 0;
		sc_pkcs15_free_tokeninfo(tokeninfo);
	}

	sc_pkcs15_parse_unusedspace(buf, buf_len, p15card);

err:
	{
		FILE *out = fopen("/tmp/output", "wb");
		if (out) {
			fprintf(out,
				"size=%zu\n"
				"buf_len=%u\n"
				"reader_data_len=%zu\n"
				"ctx_ok=%d\n"
				"card_ok=%d\n"
				"p15_ok=%d\n"
				"pubkey_decode_successes=%u\n"
				"tokeninfo_version=%u\n"
				"tokeninfo_flags=%u\n"
				"tokeninfo_label_len=%zu\n"
				"tokeninfo_serial_len=%zu\n"
				"tokeninfo_mfg_len=%zu\n",
				Size, (unsigned)buf_len, reader_data_len,
				stage_ctx_ok, stage_card_ok, stage_p15_ok,
				pubkey_decode_successes,
				tokeninfo_version, tokeninfo_flags,
				tokeninfo_label_len, tokeninfo_serial_len,
				tokeninfo_mfg_len);
			for (i = 0; i < sizeof decode_entries/sizeof *decode_entries; i++)
				fprintf(out, "decode_entry[%zu]=%u\n", i, decode_entry_successes[i]);
			fclose(out);
		} else {
			writeFailure();
		}
	}

	sc_pkcs15_card_free(p15card);
	sc_disconnect_card(card);
	sc_release_context(ctx);
	return 0;
}
