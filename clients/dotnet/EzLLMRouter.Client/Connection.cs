using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;
using static CognitiveDynamics.EzLLMRouter.Values;

namespace CognitiveDynamics.EzLLMRouter;

/// <summary>An API failure with the original selector and verified recovery evidence.</summary>
public sealed class EzLLMRouterException : Exception
{
    public string Code { get; }
    public int? HttpStatus { get; }
    public string RetryGuidance { get; }
    public string? CorrelationId { get; init; }
    public JsonObject? Selector { get; }
    public JsonObject? Handle { get; init; }
    public JsonObject? WorkKey => At(Handle, "work_key")?.DeepClone() as JsonObject;
    public string? AttemptId { get; init; }
    public string? FailureStage { get; init; }
    internal EzLLMRouterException(string code, int? status = null, string guidance = "never", JsonObject? selector = null) : base(code)
    { Code = code; HttpStatus = status; RetryGuidance = guidance; Selector = selector?.DeepClone() as JsonObject; }
}

internal sealed class Connection : IDisposable
{
    private readonly string origin;
    private readonly string token;
    private readonly HttpClient client;
    private readonly TimeSpan timeout;
    private bool closed;
    internal Connection(string origin, string token, HttpMessageHandler? handler, TimeSpan? timeout)
    {
        if (!Uri.TryCreate(origin, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.Host.Length == 0 || uri.UserInfo.Length != 0 || uri.AbsolutePath != "/" || origin.Contains('?') || origin.Contains('#') || string.IsNullOrEmpty(token) || token.Any(c => c < 33 || c > 126))
            throw new ArgumentException("A trusted HTTP(S) origin and bearer token are required");
        this.timeout = timeout ?? TimeSpan.FromSeconds(35);
        if (this.timeout < TimeSpan.Zero && this.timeout != Timeout.InfiniteTimeSpan) throw new ArgumentOutOfRangeException(nameof(timeout));
        this.origin = origin.TrimEnd('/'); this.token = token;
        bool owned = handler is null;
        handler ??= new SocketsHttpHandler { AllowAutoRedirect = false, UseProxy = false, AutomaticDecompression = DecompressionMethods.None, ConnectTimeout = TimeSpan.FromSeconds(10), PooledConnectionLifetime = TimeSpan.Zero, MaxResponseHeadersLength = 64 };
        client = new HttpClient(handler, owned) { Timeout = Timeout.InfiniteTimeSpan };
    }

    internal async Task<(JsonObject Value, int Status)> RequestAsync(string method, string path, string header, string version, JsonObject? body, Dictionary<string, string>? extra, int limit, JsonObject? selector, CancellationToken cancellationToken)
    {
        if (closed) throw new EzLLMRouterException("CLIENT_CLOSED");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        if (timeout > TimeSpan.Zero) deadline.CancelAfter(timeout);
        using var request = new HttpRequestMessage(new HttpMethod(method), origin + path);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        request.Headers.Add(header, version); request.Headers.AcceptEncoding.Add(new StringWithQualityHeaderValue("identity"));
        if (extra is not null) foreach (var (key, value) in extra) request.Headers.Add(key, value);
        if (body is not null)
        {
            request.Content = new ByteArrayContent(Encoding.UTF8.GetBytes(ProtocolJson.Stringify(body)));
            request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        }
        int? status = null;
        try
        {
            using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token).ConfigureAwait(false);
            status = (int)response.StatusCode;
            if (response.Content.Headers.ContentEncoding.Any(encoding => !encoding.Equals("identity", StringComparison.OrdinalIgnoreCase))) throw new IOException("Unsupported encoding");
            long? declared = response.Content.Headers.ContentLength;
            if (response.Content.Headers.TryGetValues("Content-Length", out var lengths))
            {
                string length = string.Join(",", lengths);
                if (length.Length == 0 || !length.All(char.IsAsciiDigit) || !long.TryParse(length, out long parsed)) throw new IOException("Invalid response length");
                declared = parsed;
            }
            if (declared.HasValue && declared.Value > limit) throw new IOException("Response limit");
            await using var input = await response.Content.ReadAsStreamAsync(deadline.Token).ConfigureAwait(false);
            using var output = new MemoryStream(); byte[] buffer = new byte[65536];
            while (true)
            {
                int count = await input.ReadAsync(buffer.AsMemory(0, Math.Min(buffer.Length, limit + 1 - (int)output.Length)), deadline.Token).ConfigureAwait(false);
                if (count == 0) break;
                output.Write(buffer, 0, count);
                if (output.Length > limit) throw new IOException("Response limit");
            }
            if (declared.HasValue && output.Length != declared.Value) throw new IOException("Response length mismatch");
            var value = ProtocolJson.ParseObject(output.ToArray());
            string field = header == "EzLLMRouter-Integration-Version" ? "integration_version" : "contract_version";
            if (!Is(At(value, field), version) || !response.Headers.TryGetValues(header, out var versions) || !versions.SequenceEqual([version])) throw new EzLLMRouterException("UNSUPPORTED_VERSION", status, "never", selector);
            return (value, status.Value);
        }
        catch (EzLLMRouterException) { throw; }
        catch (Exception error) when (error is HttpRequestException or IOException or OperationCanceledException or System.Text.Json.JsonException or InvalidOperationException or FormatException or ArgumentException)
        { throw new EzLLMRouterException("TRANSPORT_OUTCOME_UNKNOWN", status, "query_first", selector); }
    }
    public void Dispose() { if (!closed) { closed = true; client.Dispose(); } }
}
