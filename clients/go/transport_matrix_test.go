package ezllmrouter

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"
)

func runHTTPMatrix(t *testing.T, origin string) {
	raw, err := os.ReadFile(os.Getenv("EZLLMROUTER_TEST_MATRIX"))
	if err != nil {
		t.Fatal(err)
	}
	var matrix struct {
		Cases []struct {
			ID       string  `json:"id"`
			Code     *string `json:"code"`
			Guidance string  `json:"retry_guidance"`
			Statuses []int   `json:"http_status"`
			Timeout  int     `json:"timeout_ms"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &matrix); err != nil {
		t.Fatal(err)
	}
	if len(matrix.Cases) != 28 {
		t.Fatal("transport matrix inventory changed")
	}
	for _, row := range matrix.Cases {
		t.Run(row.ID, func(t *testing.T) {
			endpoint := origin
			if row.ID == "untrusted_tls" {
				endpoint = os.Getenv("EZLLMROUTER_TEST_TLS_ORIGIN")
			}
			client, err := NewClient(endpoint, "synthetic-native-"+row.ID, WithTimeout(time.Duration(row.Timeout)*time.Millisecond))
			if err != nil {
				t.Fatal(err)
			}
			defer client.Close()
			result, err := client.GetCapabilities(context.Background())
			if row.Code == nil {
				if err != nil || result["profile"] != "initial_1a@1" {
					t.Fatal("valid response rejected", err)
				}
				return
			}
			var failure *Error
			if !errors.As(err, &failure) {
				t.Fatal("invalid response accepted", row.ID)
			}
			statusOK := false
			for _, status := range row.Statuses {
				statusOK = statusOK || status == failure.HTTPStatus
			}
			if failure.Code != *row.Code || failure.RetryGuidance != row.Guidance || !statusOK {
				t.Fatalf("%s: got %s/%s/%d", row.ID, failure.Code, failure.RetryGuidance, failure.HTTPStatus)
			}
		})
	}
}
