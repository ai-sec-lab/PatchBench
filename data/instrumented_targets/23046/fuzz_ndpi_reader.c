#include "reader_util.h"
#include "ndpi_api.h"

#include <pcap/pcap.h>

#include <errno.h>
#include <stdint.h>
#include <stdio.h>

struct ndpi_workflow_prefs *prefs = NULL;

int nDPI_LogLevel = 0;
char *_debug_protocols = NULL;
u_int32_t current_ndpi_memory = 0, max_ndpi_memory = 0;
u_int8_t enable_protocol_guess = 1, enable_payload_analyzer = 0;
u_int8_t enable_joy_stats = 0;
u_int8_t human_readeable_string_len = 5;
u_int8_t max_num_udp_dissected_pkts = 16 /* 8 is enough for most protocols, Signal requires more */, max_num_tcp_dissected_pkts = 80 /* due to telnet */;

static void writeFailure(void) {
  FILE *f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}

int bufferToFile(const char * name, const uint8_t *Data, size_t Size) {
  FILE * fd;
  if (remove(name) != 0) {
    if (errno != ENOENT) {
      perror("remove failed");
      return -1;
    }
  }
  fd = fopen(name, "wb");
  if (fd == NULL) {
    perror("open failed");
    return -2;
  }
  if (fwrite (Data, 1, Size, fd) != Size) {
    fclose(fd);
    return -3;
  }
  fclose(fd);
  return 0;
}

int LLVMFuzzerTestOneInput(const uint8_t *Data, size_t Size) {
  pcap_t * pkts;
  const u_char *pkt;
  struct pcap_pkthdr *header;
  int r;
  char errbuf[PCAP_ERRBUF_SIZE];
  NDPI_PROTOCOL_BITMASK all;
  char * pcap_path = tempnam("/tmp", "fuzz-ndpi-reader");

  if (prefs == NULL) {
    prefs = calloc(sizeof(struct ndpi_workflow_prefs), 1);
    if (prefs == NULL) {
      //should not happen
      return 1;
    }
    prefs->decode_tunnels = 1;
    prefs->num_roots = 16;
    prefs->max_ndpi_flows = 1024;
    prefs->quiet_mode = 0;
  }
  bufferToFile(pcap_path, Data, Size);

  pkts = pcap_open_offline(pcap_path, errbuf);
  if (pkts == NULL) {
    writeFailure();
    remove(pcap_path);
    free(pcap_path);
    return 0;
  }
  struct ndpi_workflow * workflow = ndpi_workflow_init(prefs, pkts);
  // enable all protocols
  NDPI_BITMASK_SET_ALL(all);
  ndpi_set_protocol_detection_bitmask2(workflow->ndpi_struct, &all);
  memset(workflow->stats.protocol_counter, 0,
	 sizeof(workflow->stats.protocol_counter));
  memset(workflow->stats.protocol_counter_bytes, 0,
	 sizeof(workflow->stats.protocol_counter_bytes));
  memset(workflow->stats.protocol_flows, 0,
	 sizeof(workflow->stats.protocol_flows));
  ndpi_finalize_initalization(workflow->ndpi_struct);

  r = pcap_next_ex(pkts, &header, &pkt);
  while (r > 0) {
    if(header->caplen >= 42 /* ARP+ size */) {
      /* allocate an exact size buffer to check overflows */
      uint8_t *packet_checked = malloc(header->caplen);

      if(packet_checked) {
	memcpy(packet_checked, pkt, header->caplen);
	ndpi_workflow_process_packet(workflow, header, packet_checked, NULL);
	free(packet_checked);
      }
    }

    r = pcap_next_ex(pkts, &header, &pkt);
  }
  {
    FILE *out = fopen("/tmp/output", "wb");
    if (out) {
      const struct ndpi_stats *s = &workflow->stats;
      fprintf(out,
              "raw_packet_count=%llu\n"
              "ip_packet_count=%llu\n"
              "total_wire_bytes=%llu\n"
              "total_ip_bytes=%llu\n"
              "total_discarded_bytes=%llu\n"
              "tcp_count=%llu\n"
              "udp_count=%llu\n"
              "vlan_count=%llu\n"
              "mpls_count=%llu\n"
              "pppoe_count=%llu\n"
              "fragmented_count=%llu\n"
              "ndpi_flow_count=%u\n"
              "guessed_flow_protocols=%u\n",
              (unsigned long long)s->raw_packet_count,
              (unsigned long long)s->ip_packet_count,
              (unsigned long long)s->total_wire_bytes,
              (unsigned long long)s->total_ip_bytes,
              (unsigned long long)s->total_discarded_bytes,
              (unsigned long long)s->tcp_count,
              (unsigned long long)s->udp_count,
              (unsigned long long)s->vlan_count,
              (unsigned long long)s->mpls_count,
              (unsigned long long)s->pppoe_count,
              (unsigned long long)s->fragmented_count,
              s->ndpi_flow_count,
              s->guessed_flow_protocols);
      for (unsigned i = 0;
           i < (unsigned)(NDPI_MAX_SUPPORTED_PROTOCOLS + NDPI_MAX_NUM_CUSTOM_PROTOCOLS + 1);
           i++) {
        if (s->protocol_counter[i] || s->protocol_counter_bytes[i] || s->protocol_flows[i]) {
          fprintf(out, "proto[%u]: pkts=%llu bytes=%llu flows=%u\n",
                  i,
                  (unsigned long long)s->protocol_counter[i],
                  (unsigned long long)s->protocol_counter_bytes[i],
                  s->protocol_flows[i]);
        }
      }
      fclose(out);
    } else {
      writeFailure();
    }
  }

  ndpi_workflow_free(workflow);
  pcap_close(pkts);

  remove(pcap_path);
  free(pcap_path);

  return 0;
}

#ifdef BUILD_MAIN
int main(int argc, char ** argv)
{
  FILE * pcap_file;
  long pcap_file_size;
  uint8_t * pcap_buffer;
  int test_retval;

  if (argc != 2) {
    fprintf(stderr, "usage: %s: [pcap-file]\n",
            (argc > 0 ? argv[0] : "fuzz_ndpi_reader_with_main"));
    return 1;
  }

  pcap_file = fopen(argv[1], "r");
  if (pcap_file == NULL) {
    perror("fopen failed");
    return 1;
  }

  if (fseek(pcap_file, 0, SEEK_END) != 0) {
    perror("fseek(SEEK_END) failed");
    fclose(pcap_file);
    return 1;
  }

  pcap_file_size = ftell(pcap_file);
  if (pcap_file_size < 0) {
    perror("ftell failed");
    fclose(pcap_file);
    return 1;
  }

  if (fseek(pcap_file, 0, SEEK_SET) != 0) {
    perror("fseek(0, SEEK_SET)  failed");
    fclose(pcap_file);
    return 1;
  }

  pcap_buffer = malloc(pcap_file_size);
  if (pcap_buffer == NULL) {
    perror("malloc failed");
    fclose(pcap_file);
    return 1;
  }

  if (fread(pcap_buffer, sizeof(*pcap_buffer), pcap_file_size, pcap_file) != pcap_file_size) {
    perror("fread failed");
    fclose(pcap_file);
    return 1;
  }

  test_retval = LLVMFuzzerTestOneInput(pcap_buffer, pcap_file_size);
  fclose(pcap_file);
  free(pcap_buffer);

  return test_retval;
}
#endif
