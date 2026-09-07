/*
 * schema.c: a libFuzzer target to test the XML Schema processor.
 *
 * See Copyright for the status of this software.
 */

#include <libxml/catalog.h>
#include <libxml/xmlschemas.h>
#include <stdio.h>
#include "fuzz.h"

static void writeFailure(void) {
    FILE *f = fopen("/tmp/output", "wb");
    if (f) {
        fwrite("failed to save /tmp/output", 1, 26, f);
        fclose(f);
    }
}

int
LLVMFuzzerInitialize(int *argc ATTRIBUTE_UNUSED,
                     char ***argv ATTRIBUTE_UNUSED) {
    xmlFuzzMemSetup();
    xmlInitParser();
#ifdef LIBXML_CATALOG_ENABLED
    xmlInitializeCatalog();
#endif
    xmlSetGenericErrorFunc(NULL, xmlFuzzErrorFunc);
    xmlSetExternalEntityLoader(xmlFuzzEntityLoader);

    return 0;
}

int
LLVMFuzzerTestOneInput(const char *data, size_t size) {
    xmlSchemaParserCtxtPtr pctxt;
    size_t maxAlloc;

    if (size > 50000) {
        writeFailure();
        return(0);
    }

    maxAlloc = xmlFuzzReadInt(4) % (size + 1);

    xmlFuzzDataInit(data, size);
    xmlFuzzReadEntities();

    xmlFuzzMemSetLimit(maxAlloc);
    pctxt = xmlSchemaNewParserCtxt(xmlFuzzMainUrl());
    xmlSchemaSetParserErrors(pctxt, xmlFuzzErrorFunc, xmlFuzzErrorFunc, NULL);
    {
        xmlSchemaPtr schema = xmlSchemaParse(pctxt);
        if (schema) {
            FILE *f = fopen("/tmp/output", "wb");
            if (f) {
                xmlSchemaDump(f, schema);
                fclose(f);
            } else {
                writeFailure();
            }
        } else {
            writeFailure();
        }
        xmlSchemaFree(schema);
    }
    xmlSchemaFreeParserCtxt(pctxt);

    xmlFuzzMemSetLimit(0);
    xmlFuzzDataCleanup();
    xmlResetLastError();

    return(0);
}

