package com.cognitivedynamics.ezllmrouter;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HexFormat;
import java.util.Map;

final class DecoderCorpus {
    private DecoderCorpus() {}
    static void run(Path path) throws IOException {
        var cases = Values.array(Json.parseObject(Files.readAllBytes(path)).get("cases"));
        if (cases.size() != 536) throw new AssertionError("decoder corpus inventory changed");
        for (Object item : cases) {
            Map<String, Object> row = Values.object(item);
            String actual = null;
            try { actual = Json.stringify(Json.parseObject(HexFormat.of().parseHex(Values.text(row.get("raw_hex"))))); }
            catch (IllegalArgumentException expected) { /* A protocol rejection is an observed outcome. */ }
            if (!java.util.Objects.equals(actual, row.get("canonical")))
                throw new AssertionError("decoder corpus mismatch: " + row.get("id"));
        }
        System.out.println("Java: " + cases.size() + " independent decoder cases passed.");
    }
}
