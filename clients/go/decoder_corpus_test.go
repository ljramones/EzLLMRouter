package ezllmrouter

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestIndependentDecoderCorpus(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "tests", "fixtures", "contracts", "transport-security", "decoder_cases.json"))
	if err != nil {
		t.Fatal(err)
	}
	var policy struct {
		Cases []struct {
			ID        string  `json:"id"`
			Raw       string  `json:"raw_hex"`
			Canonical *string `json:"canonical"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &policy); err != nil {
		t.Fatal(err)
	}
	if len(policy.Cases) != 536 {
		t.Fatal("decoder corpus inventory changed")
	}
	for _, row := range policy.Cases {
		t.Run(row.ID, func(t *testing.T) {
			body, err := hex.DecodeString(row.Raw)
			if err != nil {
				t.Fatal(err)
			}
			value, err := ParseObject(body)
			if row.Canonical == nil {
				if err == nil {
					t.Fatal("invalid input accepted")
				}
				return
			}
			if err != nil {
				t.Fatal("valid input rejected", err)
			}
			actual, err := canonical(value)
			if err != nil || string(actual) != *row.Canonical {
				t.Fatal("decoded value differs from independent oracle")
			}
		})
	}
}
