using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace CognitiveDynamics.EzLLMRouter;

/// <summary>Strict integer-only protocol JSON; monetary and vector decimals remain strings.</summary>
public static class ProtocolJson
{
    internal const long MaxInteger = 9007199254740991;
    private static readonly Regex Integer = new(@"^-?(0|[1-9][0-9]*)$", RegexOptions.CultureInvariant);

    public static JsonObject ParseObject(ReadOnlyMemory<byte> bytes)
    {
        using var document = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 33 });
        Check(document.RootElement, 0);
        return JsonNode.Parse(bytes.Span) as JsonObject ?? throw new JsonException("JSON object required");
    }

    public static JsonObject ParseObject(string text) => ParseObject(new UTF8Encoding(false, true).GetBytes(text));

    private static void Check(JsonElement value, int depth)
    {
        if (depth > 32) throw new JsonException("JSON depth limit");
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                var keys = new HashSet<string>(StringComparer.Ordinal);
                foreach (var member in value.EnumerateObject())
                {
                    if (!Scalar(member.Name) || !keys.Add(member.Name)) throw new JsonException("Invalid or duplicate JSON key");
                    Check(member.Value, depth + 1);
                }
                break;
            case JsonValueKind.Array:
                foreach (var item in value.EnumerateArray()) Check(item, depth + 1);
                break;
            case JsonValueKind.String:
                if (!Scalar(value.GetString()!)) throw new JsonException("Invalid JSON scalar");
                break;
            case JsonValueKind.Number:
                if (!Integer.IsMatch(value.GetRawText()) || !value.TryGetInt64(out long n) || n < -MaxInteger || n > MaxInteger)
                    throw new JsonException("Unsafe or noninteger JSON number");
                break;
        }
    }

    internal static bool Scalar(string text)
    {
        for (int i = 0; i < text.Length; i++)
        {
            char c = text[i];
            if (c == 0) return false;
            if (char.IsHighSurrogate(c))
            {
                if (++i >= text.Length || !char.IsLowSurrogate(text[i])) return false;
            }
            else if (char.IsLowSurrogate(c)) return false;
        }
        return true;
    }

    public static string Stringify(JsonNode? value)
    {
        var output = new StringBuilder();
        Write(output, value, 0);
        return output.ToString();
    }

    private static void Quote(StringBuilder output, string text)
    {
        if (!Scalar(text)) throw new JsonException("Invalid JSON scalar");
        output.Append('"');
        foreach (char c in text)
        {
            switch (c)
            {
                case '"': case '\\': output.Append('\\').Append(c); break;
                case '\b': output.Append("\\b"); break;
                case '\f': output.Append("\\f"); break;
                case '\n': output.Append("\\n"); break;
                case '\r': output.Append("\\r"); break;
                case '\t': output.Append("\\t"); break;
                default:
                    if (c < 32) output.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    else output.Append(c);
                    break;
            }
        }
        output.Append('"');
    }

    private static int CompareKeys(string left, string right)
    {
        var a = left.EnumerateRunes().GetEnumerator(); var b = right.EnumerateRunes().GetEnumerator();
        while (true)
        {
            bool moreA = a.MoveNext(), moreB = b.MoveNext();
            if (!moreA || !moreB) return moreA.CompareTo(moreB);
            int comparison = a.Current.Value.CompareTo(b.Current.Value);
            if (comparison != 0) return comparison;
        }
    }

    private static void Write(StringBuilder output, JsonNode? value, int depth)
    {
        if (depth > 32) throw new JsonException("JSON depth limit");
        if (value is null) { output.Append("null"); return; }
        if (value is JsonObject obj)
        {
            output.Append('{'); bool first = true;
            foreach (string key in obj.Select(pair => pair.Key).Order(Comparer<string>.Create(CompareKeys)))
            {
                if (!first) output.Append(','); first = false; Quote(output, key); output.Append(':'); Write(output, obj[key], depth + 1);
            }
            output.Append('}'); return;
        }
        if (value is JsonArray array)
        {
            output.Append('['); bool first = true;
            foreach (var item in array) { if (!first) output.Append(','); first = false; Write(output, item, depth + 1); }
            output.Append(']'); return;
        }
        if (value.GetValueKind() == JsonValueKind.String) { Quote(output, value.GetValue<string>()); return; }
        string raw = value.ToJsonString();
        if (raw is "true" or "false") { output.Append(raw); return; }
        if (!Integer.IsMatch(raw) || !long.TryParse(raw, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out long number) || number < -MaxInteger || number > MaxInteger)
            throw new JsonException("Unsafe or noninteger JSON number");
        output.Append(number.ToString(CultureInfo.InvariantCulture));
    }

    internal static JsonObject Snapshot(JsonObject value) => ParseObject(Stringify(value));
    internal static string Digest(JsonObject value) => "sha256:" + Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(Stringify(value))));
}

internal static class Values
{
    internal static JsonNode? At(JsonNode? value, string key) => (value as JsonObject)?[key];
    internal static string Text(JsonNode? value) => value is JsonValue v && v.TryGetValue<string>(out var text) ? text ?? "" : "";
    internal static long Number(JsonNode? value) => long.TryParse(value?.ToJsonString(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out long n) ? n : 0;
    internal static bool Has(JsonNode? value, string key) => value is JsonObject obj && obj.ContainsKey(key);
    internal static IEnumerable<JsonNode?> Items(JsonNode? value) => value is JsonArray array ? array : Enumerable.Empty<JsonNode?>();
    internal static bool Eq(JsonNode? a, JsonNode? b) => JsonNode.DeepEquals(a, b);
    internal static bool Is(JsonNode? value, string text) => Text(value) == text;
    internal static bool Id(JsonNode? value) => value?.GetValueKind() == JsonValueKind.String && Regex.IsMatch(Text(value), @"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\z", RegexOptions.CultureInvariant);
    internal static bool Positive(JsonNode? value) => value?.GetValueKind() == JsonValueKind.Number && Number(value) > 0 && Number(value) <= ProtocolJson.MaxInteger;
    internal static bool Utc(JsonNode? value) => DateTimeOffset.TryParseExact(Text(value), "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out _);
    internal static bool One(JsonNode? value, params string[] choices) => choices.Contains(Text(value), StringComparer.Ordinal);
    internal static bool Keys(JsonNode? value, string[] required, params string[] optional) => value is JsonObject obj && required.All(obj.ContainsKey) && obj.All(pair => required.Contains(pair.Key) || optional.Contains(pair.Key));
    internal static bool Ids(JsonNode? value, params string[] keys) => keys.All(key => Id(At(value, key)));
}
