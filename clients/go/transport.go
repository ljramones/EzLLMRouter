package ezllmrouter

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

// Error carries recovery evidence. HTTPStatus is zero when no status was observed.
// Selector survives an unknown outcome; Handle is attached only after correspondence checks.
type Error struct {
	Code          string
	HTTPStatus    int
	RetryGuidance string
	CorrelationID string
	Selector      Object
	Handle        Object
	WorkKey       Object
	AttemptID     string
	FailureStage  string
}

func (e *Error) Error() string { return e.Code }
func problem(code string, status int, guidance string, selector Object) *Error {
	return &Error{Code: code, HTTPStatus: status, RetryGuidance: guidance, Selector: selector}
}

// Option configures a client before use.
type Option func(*config) error
type config struct {
	transport http.RoundTripper
	timeout   time.Duration
}

// WithTransport injects a transport, which must not follow redirects or replay requests.
// Its owner remains responsible for transport lifecycle and buffering before RoundTrip returns.
func WithTransport(transport http.RoundTripper) Option {
	return func(c *config) error {
		if transport == nil {
			return fmt.Errorf("transport is required")
		}
		c.transport = transport
		return nil
	}
}

// WithTimeout bounds the entire exchange, including response reads. Zero disables the deadline.
func WithTimeout(timeout time.Duration) Option {
	return func(c *config) error {
		if timeout < 0 {
			return fmt.Errorf("negative timeout")
		}
		c.timeout = timeout
		return nil
	}
}

type connection struct {
	origin    string
	token     string
	transport http.RoundTripper
	owned     *http.Transport
	timeout   time.Duration
	closed    atomic.Bool
}

func connect(origin, token string, options []Option) (*connection, error) {
	u, err := url.Parse(origin)
	validToken := token != "" && strings.IndexFunc(token, func(r rune) bool { return r < 33 || r > 126 }) < 0
	if err != nil || u == nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil || (u.Path != "" && u.Path != "/") || u.RawPath != "" || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || strings.Contains(origin, "#") || strings.Contains(origin, "?") || !validToken {
		return nil, fmt.Errorf("an HTTP(S) origin and bearer token are required")
	}
	cfg := config{timeout: 35 * time.Second}
	for _, option := range options {
		if option == nil {
			return nil, fmt.Errorf("nil option")
		}
		if err := option(&cfg); err != nil {
			return nil, err
		}
	}
	c := &connection{origin: strings.TrimSuffix(origin, "/"), token: token, transport: cfg.transport, timeout: cfg.timeout}
	if c.transport == nil {
		c.owned = &http.Transport{Proxy: nil, DialContext: (&net.Dialer{Timeout: 10 * time.Second}).DialContext, TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 35 * time.Second, DisableCompression: true, DisableKeepAlives: true, MaxResponseHeaderBytes: 64 * 1024}
		c.transport = c.owned
	}
	return c, nil
}
func (c *connection) close() {
	if c.closed.CompareAndSwap(false, true) && c.owned != nil {
		c.owned.CloseIdleConnections()
	}
}
func (c *connection) request(ctx context.Context, method, path, header, version string, body Object, extra http.Header, limit int, selector Object) (Object, int, error) {
	if c.closed.Load() {
		return nil, 0, problem("CLIENT_CLOSED", 0, "never", selector)
	}
	var data []byte
	var err error
	if body != nil {
		data, err = canonical(body)
		if err != nil {
			return nil, 0, problem("SCHEMA_INVALID", 0, "never", selector)
		}
	}
	if ctx == nil {
		return nil, 0, problem("SCHEMA_INVALID", 0, "never", selector)
	}
	if c.timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, c.timeout)
		defer cancel()
	}
	request, err := http.NewRequestWithContext(ctx, method, c.origin+path, bytes.NewReader(data))
	if err != nil {
		return nil, 0, problem("SCHEMA_INVALID", 0, "never", selector)
	}
	request.Header.Set("Authorization", "Bearer "+c.token)
	request.Header.Set(header, version)
	request.Header.Set("Accept-Encoding", "identity")
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	for k, values := range extra {
		request.Header[k] = append([]string(nil), values...)
	}
	response, err := c.transport.RoundTrip(request)
	if err != nil {
		if response != nil && response.Body != nil {
			response.Body.Close()
		}
		return nil, 0, problem("TRANSPORT_OUTCOME_UNKNOWN", 0, "query_first", selector)
	}
	if response == nil {
		return nil, 0, problem("TRANSPORT_OUTCOME_UNKNOWN", 0, "query_first", selector)
	}
	status := response.StatusCode
	unknown := func() (Object, int, error) {
		return nil, status, problem("TRANSPORT_OUTCOME_UNKNOWN", status, "query_first", selector)
	}
	if response.Body == nil {
		return unknown()
	}
	defer response.Body.Close()
	encodings := response.Header.Values("Content-Encoding")
	if len(encodings) > 0 && (len(encodings) != 1 || !strings.EqualFold(strings.TrimSpace(encodings[0]), "identity")) {
		return unknown()
	}
	declared := response.Header.Get("Content-Length")
	length := response.ContentLength
	if declared != "" {
		if strings.Trim(declared, "0123456789") != "" {
			return unknown()
		}
		length, err = strconv.ParseInt(declared, 10, 64)
		if err != nil {
			return unknown()
		}
	}
	if length > int64(limit) {
		return unknown()
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, int64(limit)+1))
	if err != nil || len(raw) > limit || length >= 0 && int64(len(raw)) != length {
		return unknown()
	}
	parsed, err := decode(raw)
	if err != nil {
		return unknown()
	}
	value := object(parsed)
	bodyVersion := "contract_version"
	if header == "EzLLMRouter-Integration-Version" {
		bodyVersion = "integration_version"
	}
	versions := response.Header.Values(header)
	if value == nil || value[bodyVersion] != version || len(versions) != 1 || versions[0] != version {
		return nil, status, problem("UNSUPPORTED_VERSION", status, "never", selector)
	}
	return value, status, nil
}

func errorEvidence(value Object, status int, selector, handle Object) *Error {
	e := problem(str(value["code"]), status, str(value["retry_guidance"]), selector)
	e.CorrelationID = str(value["correlation_id"])
	e.Handle = handle
	if handle != nil {
		e.WorkKey = field(handle, "work_key")
	}
	return e
}
func protocolError(status int, selector, handle Object) *Error {
	e := problem("PROTOCOL_INVALID", status, "query_first", selector)
	e.Handle = handle
	if handle != nil {
		e.WorkKey = field(handle, "work_key")
	}
	return e
}

// IsUnknownOutcome reports whether callers must query existing work before deciding on redelivery.
func IsUnknownOutcome(err error) bool {
	var e *Error
	return errors.As(err, &e) && e.RetryGuidance == "query_first"
}
