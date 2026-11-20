using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using static CognitiveDynamics.EzLLMRouter.Values;

namespace CognitiveDynamics.EzLLMRouter;

internal static class Schema
{
    private static readonly Dictionary<string, JsonObject> Bundles = Load();
    private static readonly ConcurrentDictionary<string, Regex> Patterns = new();
    private static Dictionary<string, JsonObject> Load()
    {
        var result = new Dictionary<string, JsonObject>();
        foreach (var (version, name) in new Dictionary<string, string> { ["0.2"] = "wire02.json", ["0.3"] = "dev12_schemas.json", ["1"] = "integration_schema.json", ["2"] = "integration_schema_v2.json", ["3"] = "integration_schema_v3.json" })
        {
            using var input = typeof(Schema).Assembly.GetManifestResourceStream("CognitiveDynamics.EzLLMRouter.Schemas." + name) ?? throw new InvalidOperationException("Missing embedded schema");
            result[version] = JsonNode.Parse(input)!["$defs"]!.AsObject();
        }
        return result;
    }
    internal static bool Policy(JsonNode? value, bool nulls, bool controls)
    {
        if (value is null) return nulls;
        if (value is JsonObject obj) return obj.All(e => (!controls || e.Key.All(c => c >= 32 && c != 127)) && Policy(e.Value, nulls, controls));
        if (value is JsonArray array) return array.All(item => Policy(item, nulls, controls));
        return !controls || value.GetValueKind() != System.Text.Json.JsonValueKind.String || Text(value).All(c => c >= 32 && c != 127);
    }
    internal static bool Named(JsonNode? value, string version, string name) => (version != "0.3" || Policy(value, true, true)) && Bundles.TryGetValue(version, out var defs) && defs[name] is JsonObject shape && Match(value, shape, defs);
    private static long Bound(JsonNode? shape, string key, long fallback) => Has(shape, key) ? Number(At(shape, key)) : fallback;
    private static bool Match(JsonNode? value, JsonNode? shape, JsonObject defs)
    {
        if (Has(shape, "$ref"))
        {
            string reference = Text(At(shape, "$ref"));
            if (!reference.StartsWith("#/$defs/", StringComparison.Ordinal)) return false;
            string name = reference[8..];
            if (name == "PublicText" && value?.GetValueKind() == System.Text.Json.JsonValueKind.String && Text(value).Any(c => c < 32 || c == 127)) return false;
            return defs[name] is JsonNode target && (name is not ("utc" or "UtcSecond") || Utc(value)) && Match(value, target, defs);
        }
        if (Items(At(shape, "allOf")).Any(part => !Match(value, part, defs))) return false;
        if (Has(shape, "anyOf") && !Items(At(shape, "anyOf")).Any(part => Match(value, part, defs))) return false;
        if (Has(shape, "oneOf") && Items(At(shape, "oneOf")).Count(part => Match(value, part, defs)) != 1) return false;
        if (Has(shape, "not") && Match(value, At(shape, "not"), defs)) return false;
        if (Has(shape, "if"))
        {
            string branch = Match(value, At(shape, "if"), defs) ? "then" : "else";
            if (Has(shape, branch) && !Match(value, At(shape, branch), defs)) return false;
        }
        if (Has(shape, "const") && !Eq(value, At(shape, "const"))) return false;
        if (Has(shape, "enum") && !Items(At(shape, "enum")).Any(item => Eq(item, value))) return false;
        if (value is JsonObject obj)
        {
            if (Items(At(shape, "required")).Any(key => !obj.ContainsKey(Text(key)))) return false;
            var properties = At(shape, "properties");
            foreach (var (key, item) in obj)
            {
                if (Has(properties, key)) { if (!Match(item, At(properties, key), defs)) return false; }
                else if (At(shape, "additionalProperties")?.ToJsonString() == "false") return false;
                else if (At(shape, "additionalProperties") is JsonObject extra && !Match(item, extra, defs)) return false;
            }
        }
        switch (Text(At(shape, "type")))
        {
            case "object": return value is JsonObject;
            case "array":
                return value is JsonArray a && a.Count >= Bound(shape, "minItems", 0) && a.Count <= Bound(shape, "maxItems", ProtocolJson.MaxInteger)
                    && (!IsTrue(At(shape, "uniqueItems")) || a.Select(ProtocolJson.Stringify).Distinct(StringComparer.Ordinal).Count() == a.Count)
                    && (!Has(shape, "items") || a.All(item => Match(item, At(shape, "items"), defs)));
            case "string":
                string text = Text(value); int length = text.EnumerateRunes().Count();
                return value?.GetValueKind() == System.Text.Json.JsonValueKind.String && ProtocolJson.Scalar(text) && length >= Bound(shape, "minLength", 0) && length <= Bound(shape, "maxLength", ProtocolJson.MaxInteger)
                    && (!Has(shape, "pattern") || Patterns.GetOrAdd(Text(At(shape, "pattern")),
                        pattern => new Regex(pattern.EndsWith('$') ? pattern[..^1] + @"\z" : pattern, RegexOptions.CultureInvariant)).IsMatch(text));
            case "integer": return value?.GetValueKind() == System.Text.Json.JsonValueKind.Number && Number(value) >= Bound(shape, "minimum", -ProtocolJson.MaxInteger) && Number(value) <= Bound(shape, "maximum", ProtocolJson.MaxInteger);
            case "boolean": return value?.GetValueKind() is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False;
            case "null": return value is null;
            default: return true;
        }
    }
    internal static bool IsTrue(JsonNode? value) => value?.ToJsonString() == "true";
}
