package ezllmrouter

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type observedBody struct {
	io.Reader
	closed bool
	reads  int
}

func (b *observedBody) Read(p []byte) (int, error) { b.reads++; return b.Reader.Read(p) }
func (b *observedBody) Close() error               { b.closed = true; return nil }

func invoke(ctx context.Context, c *Client, i *IntegrationClient, test Object) (Object, error) {
	args := array(test["args"])
	arg := func(n int) Object { return object(args[n]) }
	s := func(n int) string { return str(args[n]) }
	var options *SubmitOptions
	if has(test, "wait_ms") {
		wait := int(integer(test["wait_ms"]))
		options = &SubmitOptions{WaitMS: &wait}
	}
	switch test["action"] {
	case "submit":
		return c.Submit(ctx, arg(0), options)
	case "submit_in_run":
		return c.SubmitInRun(ctx, arg(0), s(1), options)
	case "get_status":
		return c.GetStatus(ctx, arg(0))
	case "get_capabilities":
		return c.GetCapabilities(ctx)
	case "submit_embedding":
		return c.SubmitEmbedding(ctx, arg(0), options)
	case "submit_rerank":
		return c.SubmitRerank(ctx, arg(0), options)
	case "get_successor_status":
		return c.GetSuccessorStatus(ctx, arg(0))
	case "start_run":
		return c.StartRun(ctx, arg(0))
	case "get_run":
		return c.GetRun(ctx, s(0))
	case "report_outcome":
		return c.ReportOutcome(ctx, arg(0))
	case "get_outcome_receipt":
		return c.GetOutcomeReceipt(ctx, s(0))
	case "create_dataset":
		return i.CreateDataset(ctx, arg(0))
	case "register_account":
		return i.RegisterAccount(ctx, arg(0))
	case "set_account_state":
		return i.SetAccountState(ctx, s(0), arg(1))
	case "set_account_permissions":
		return i.SetAccountPermissions(ctx, s(0), arg(1))
	case "submit_observation":
		return i.SubmitObservation(ctx, arg(0))
	case "recover_receipt":
		return i.RecoverReceipt(ctx, s(0), s(1))
	case "eligibility":
		return i.Eligibility(ctx, s(0), s(1), s(2))
	case "operation_eligibility":
		return i.OperationEligibility(ctx, s(0), s(1), arg(2))
	case "report":
		return i.Report(ctx, s(0))
	case "submit_snapshot":
		return i.SubmitSnapshot(ctx, arg(0))
	case "snapshot":
		return i.Snapshot(ctx, s(0), s(1))
	case "export_dataset":
		return i.ExportDataset(ctx, s(0))
	}
	panic("unknown case action")
}
func TestContractParity(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "tests", "client_languages", "cases.json"))
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	for _, item := range array(parsed) {
		test := object(item)
		t.Run(str(test["name"]), func(t *testing.T) {
			expected := field(test, "expected")
			calls := array(expected["calls"])
			count := 0
			var observed *observedBody
			transport := roundTripFunc(func(request *http.Request) (*http.Response, error) {
				count++
				if count > len(calls) {
					t.Fatal("unexpected transport invocation")
				}
				call := object(calls[count-1])
				if request.Method != call["method"] {
					t.Errorf("method: %s", request.Method)
				}
				// Percent-encoding case and literal colons have equivalent routing meaning.
				gotPath, _ := url.PathUnescape(request.URL.RequestURI())
				wantPath, _ := url.PathUnescape(str(call["path"]))
				if gotPath != wantPath {
					t.Errorf("path %s != %s", gotPath, wantPath)
				}
				for k, v := range field(call, "headers") {
					if request.Header.Get(k) != str(v) {
						t.Errorf("header %s", k)
					}
				}
				body, _ := io.ReadAll(request.Body)
				if call["body"] == nil {
					if len(body) != 0 {
						t.Error("unexpected body")
					}
				} else {
					v, err := decode(body)
					if err != nil || !equal(v, call["body"]) {
						t.Error("request body mismatch")
					}
				}
				if test["lost"] == true {
					return nil, errors.New("synthetic lost response")
				}
				responseHeaders := http.Header{}
				version := str(test["wire"])
				if version == "" {
					version = "0.2"
				}
				responseHeaders.Set("Duranki-Contract-Version", version)
				version = str(test["version"])
				if version == "" {
					version = "1"
				}
				responseHeaders.Set("Duranki-Integration-Version", version)
				for k, v := range field(test, "response_headers") {
					responseHeaders.Set(k, str(v))
				}
				content, _ := canonical(test["response"])
				if has(test, "raw") {
					content, _ = base64.StdEncoding.DecodeString(str(test["raw"]))
				}
				observed = &observedBody{Reader: bytes.NewReader(content)}
				status := int(integer(test["status"]))
				if status == 0 {
					status = 200
				}
				return &http.Response{StatusCode: status, Header: responseHeaders, Body: observed, ContentLength: -1}, nil
			})
			c, err := NewClient("http://synthetic.invalid", "synthetic-token", WithTransport(transport))
			if err != nil {
				t.Fatal(err)
			}
			defer c.Close()
			version := str(test["version"])
			if version == "" {
				version = "1"
			}
			i, err := NewIntegrationClient("http://synthetic.invalid", "synthetic-token", version, WithTransport(transport))
			if err != nil {
				t.Fatal(err)
			}
			defer i.Close()
			result, err := invoke(context.Background(), c, i, test)
			if expected["ok"] == true {
				if err != nil {
					t.Fatal(err)
				}
				want := test["response"]
				action := str(test["action"])
				if action == "start_run" || action == "get_run" {
					want = field(test, "response")["run"]
				}
				if action == "report_outcome" || action == "get_outcome_receipt" {
					want = field(test, "response")["receipt"]
				}
				if !equal(result, want) {
					t.Error("result mismatch")
				}
			} else {
				var failure *Error
				if !errors.As(err, &failure) {
					t.Fatalf("expected %v, got %v", expected["code"], err)
				}
				if failure.Code != expected["code"] || failure.RetryGuidance != expected["retry_guidance"] || failure.HTTPStatus != int(integer(expected["http_status"])) {
					t.Errorf("error %#v, expected %#v", failure, expected)
				}
				if !equal(failure.Selector, object(expected["selector"])) || !equal(failure.Handle, object(expected["handle"])) {
					t.Error("recovery evidence mismatch")
				}
			}
			if count != len(calls) {
				t.Errorf("calls %d != %d", count, len(calls))
			}
			if observed != nil && !observed.closed {
				t.Error("response body not closed")
			}
			if observed != nil && (test["name"] == "oversize" || test["name"] == "compressed") && observed.reads != 0 {
				t.Error("rejected headers read body")
			}
		})
	}
}
func TestConfigurationAndLifecycle(t *testing.T) {
	for _, origin := range []string{"file:///tmp/a", "https://user:password@example.com", "http://example.com/path", "http://example.com?x=1", "http://example.com#fragment", "http://example.com?", "http://example.com#"} {
		if c, err := NewClient(origin, "synthetic-token"); err == nil {
			c.Close()
			t.Errorf("accepted %s", origin)
		}
	}
	c, err := NewClient("https://example.com", "synthetic-token")
	if err != nil {
		t.Fatal(err)
	}
	c.Close()
	_, err = c.GetCapabilities(context.Background())
	var failure *Error
	if !errors.As(err, &failure) || failure.Code != "CLIENT_CLOSED" {
		t.Fatal("closed client used transport")
	}
}
func TestJSONAndCanonicalDigest(t *testing.T) {
	for _, s := range []string{`{"a":1,"a":2}`, `{"a":"\ud800"}`, `{"a":"\udc00"}`, `{"a":"\ud800\u0041"}`, `{"a":1.0}`, `{"a":1e0}`, `{"a":9007199254740992}`, `{"a":01}`, `{"a":true} garbage`} {
		if _, err := decode([]byte(s)); err == nil {
			t.Errorf("accepted %s", s)
		}
	}
	v, err := decode([]byte(`{"x":"\ud83d\ude00"}`))
	if err != nil || field(object(v), "missing") != nil || object(v)["x"] != "😀" {
		t.Fatal("valid Unicode pair rejected")
	}
	raw, err := canonical(Object{"z": "<>&\u2028", "a": "é", "n": int64(7)})
	if err != nil || string(raw) != `{"a":"é","n":7,"z":"<>&`+"\u2028"+`"}` {
		t.Fatal("canonical Unicode mismatch", string(raw), err)
	}
}
func TestResponseBoundAndCancellation(t *testing.T) {
	body := &observedBody{Reader: strings.NewReader(strings.Repeat("x", 1024*1024+1))}
	transport := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: http.Header{}, Body: body, ContentLength: -1}, nil
	})
	c, _ := NewClient("http://synthetic.invalid", "token", WithTransport(transport))
	defer c.Close()
	_, err := c.GetCapabilities(context.Background())
	if !IsUnknownOutcome(err) || !body.closed {
		t.Fatal("overflow not bounded")
	}
	canceled := roundTripFunc(func(request *http.Request) (*http.Response, error) {
		<-request.Context().Done()
		return nil, request.Context().Err()
	})
	c, _ = NewClient("http://synthetic.invalid", "token", WithTransport(canceled), WithTimeout(time.Millisecond))
	defer c.Close()
	_, err = c.GetCapabilities(context.Background())
	if !IsUnknownOutcome(err) {
		t.Fatal("timeout not uncertain")
	}
}

func TestHTTPTransport(t *testing.T) {
	origin := os.Getenv("EZLLMROUTER_TEST_ORIGIN")
	if origin == "" {
		t.Skip("explicit loopback fixture required")
	}
	for _, mode := range []string{"success", "redirect", "compressed", "oversize", "chunked", "truncated", "slow"} {
		t.Run(mode, func(t *testing.T) {
			options := []Option{}
			if mode == "slow" {
				options = append(options, WithTimeout(150*time.Millisecond))
			}
			c, err := NewClient(origin, "synthetic-native-"+mode, options...)
			if err != nil {
				t.Fatal(err)
			}
			defer c.Close()
			result, err := c.GetCapabilities(context.Background())
			if mode == "success" || mode == "chunked" {
				if err != nil || result["profile"] != "initial_1a@1" {
					t.Fatal(result, err)
				}
				return
			}
			var failure *Error
			if !errors.As(err, &failure) || failure.RetryGuidance != "query_first" {
				t.Fatal("response not rejected", err)
			}
			expected := "TRANSPORT_OUTCOME_UNKNOWN"
			if mode == "redirect" {
				expected = "INTERNAL_UNAVAILABLE"
			}
			if failure.Code != expected {
				t.Fatal(failure)
			}
		})
	}
}

func TestLargeEmbeddingUsesRequestProfileAndSuccessorLimit(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "tests", "client_languages", "cases.json"))
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	var sample Object
	for _, row := range array(parsed) {
		if object(row)["name"] == "embedding" {
			sample = object(row)
			break
		}
	}
	if sample == nil {
		t.Fatal("missing contract case")
	}
	request := object(array(sample["args"])[0])
	input := field(request, "input")
	profile := field(input, "profile")
	profile["dimensions"] = int64(2048)
	profile["profile_id"] = "profile.new"
	profile["model_ref"] = "model.new"
	request["requested_configuration_ref"] = "cfg.new"
	reply := field(sample, "response")
	result := field(reply, "result")
	result["dimensions"] = int64(2048)
	result["profile_id"] = "profile.new"
	result["model_ref"] = "model.new"
	items, vectors := []any{}, []any{}
	for i := 0; i < 25; i++ {
		id := "item." + strconv.Itoa(i)
		items = append(items, Object{"item_id": id, "text": "synthetic"})
		values := make([]any, 2048)
		for n := range values {
			values[n] = "0.1234567890123456"
		}
		vectors = append(vectors, Object{"item_id": id, "input_index": int64(i), "values": values})
	}
	input["items"] = items
	result["vectors"] = vectors
	content, err := canonical(reply)
	if err != nil || len(content) <= 1024*1024 {
		t.Fatal("fixture must exercise the successor response limit")
	}
	calls := 0
	transport := roundTripFunc(func(*http.Request) (*http.Response, error) {
		calls++
		return &http.Response{StatusCode: 200, Header: http.Header{"Duranki-Contract-Version": []string{"0.3"}}, Body: io.NopCloser(bytes.NewReader(content)), ContentLength: int64(len(content))}, nil
	})
	c, _ := NewClient("http://synthetic.invalid", "token", WithTransport(transport))
	defer c.Close()
	value, err := c.SubmitEmbedding(context.Background(), request, nil)
	if err != nil || len(array(field(value, "result")["vectors"])) != 25 || calls != 1 {
		t.Fatal("valid large request-bound result rejected", err)
	}
}
