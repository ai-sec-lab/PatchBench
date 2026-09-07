/*
Copyright (c) 2017. The YARA Authors. All Rights Reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation and/or
other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
may be used to endorse or promote products derived from this software without
specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*/

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#include <stdio.h>

#include <yara.h>

static void writeFailure() {
  FILE* f = fopen("/tmp/output", "wb");
  if (f) {
    fwrite("failed to save /tmp/output", 1, 26, f);
    fclose(f);
  }
}


extern "C" int LLVMFuzzerInitialize(int* argc, char*** argv)
{
   yr_initialize();
  return 0;
}


extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
  YR_RULES* rules;
  YR_COMPILER* compiler;

  char* buffer = (char*) malloc(size + 1);

  if (!buffer)
  {
    writeFailure();
    return 0;
  }

  strncpy(buffer, (const char *) data, size);
  buffer[size] = 0;

  if (yr_compiler_create(&compiler) != ERROR_SUCCESS)
  {
    writeFailure();
    free(buffer);
    return 0;
  }

  int wrote_output = 0;
  int errors = yr_compiler_add_string(compiler, (const char*) buffer, NULL);
  if (errors == 0)
  {
    if (yr_compiler_get_rules(compiler, &rules) == ERROR_SUCCESS)
    {
      FILE* out = fopen("/tmp/output", "wb");
      if (out)
      {
        YR_RULE* rule;
        int nrules = 0;
        yr_rules_foreach(rules, rule) nrules++;
        fprintf(out, "compile_errors=0\nrules=%d\n", nrules);
        yr_rules_foreach(rules, rule)
        {
          fprintf(out, "rule %s ns=%s g_flags=%d num_atoms=%d\n",
                  rule->identifier ? rule->identifier : "(null)",
                  (rule->ns && rule->ns->name) ? rule->ns->name : "(null)",
                  rule->g_flags, rule->num_atoms);
          YR_STRING* str;
          yr_rule_strings_foreach(rule, str)
          {
            fprintf(out, "  string %s len=%d g_flags=%d\n",
                    str->identifier ? str->identifier : "(null)",
                    str->length, str->g_flags);
          }
        }
        fclose(out);
        wrote_output = 1;
      }
      yr_rules_destroy(rules);
    }
  }
  if (!wrote_output)
  {
    FILE* out = fopen("/tmp/output", "wb");
    if (out)
    {
      fprintf(out, "compile_errors=%d\nrules=0\n", errors);
      fclose(out);
    }
    else
    {
      writeFailure();
    }
  }

  yr_compiler_destroy(compiler);
  free(buffer);

  return 0;
}
