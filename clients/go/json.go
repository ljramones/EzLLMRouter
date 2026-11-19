package ezllmrouter

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Object is a protocol record. Decimal amounts and vector coordinates remain strings.
type Object = map[string]any

const maxInteger int64 = 9007199254740991

// ParseObject decodes a protocol record, preserving safe integers and rejecting ambiguous JSON.
func ParseObject(raw []byte) (Object, error) {
	value, err := decode(raw)
	if err != nil {
		return nil, err
	}
	result := object(value)
	if result == nil {
		return nil, fmt.Errorf("JSON object required")
	}
	return result, nil
}

func object(v any) Object           { m, _ := v.(map[string]any); return m }
func array(v any) []any             { a, _ := v.([]any); return a }
func str(v any) string              { s, _ := v.(string); return s }
func integer(v any) int64           { n, _ := v.(int64); return n }
func has(m Object, key string) bool { _, ok := m[key]; return ok }
func equal(a, b any) bool           { return reflect.DeepEqual(a, b) }
func contains(values []any, value any) bool {
	for _, v := range values {
		if equal(v, value) {
			return true
		}
	}
	return false
}
func field(m Object, key string) Object { return object(m[key]) }
func scalar(s string) bool {
	if !utf8.ValidString(s) {
		return false
	}
	for _, r := range s {
		if r < 32 || r == 127 {
			return false
		}
	}
	return true
}

// encoding/json replaces unpaired escaped surrogates; reject them before decoding.
func surrogateCheck(raw []byte) error {
	for i := 0; i < len(raw); i++ {
		if raw[i] != '"' {
			continue
		}
		i++
		for ; i < len(raw) && raw[i] != '"'; i++ {
			if raw[i] != '\\' {
				continue
			}
			i++
			if i >= len(raw) {
				return fmt.Errorf("invalid escape")
			}
			if raw[i] != 'u' {
				continue
			}
			if i+4 >= len(raw) {
				return fmt.Errorf("invalid unicode escape")
			}
			n, err := strconv.ParseUint(string(raw[i+1:i+5]), 16, 16)
			if err != nil {
				return err
			}
			i += 4
			if n >= 0xdc00 && n <= 0xdfff {
				return fmt.Errorf("unpaired surrogate")
			}
			if n >= 0xd800 && n <= 0xdbff {
				if i+6 >= len(raw) || raw[i+1] != '\\' || raw[i+2] != 'u' {
					return fmt.Errorf("unpaired surrogate")
				}
				low, err := strconv.ParseUint(string(raw[i+3:i+7]), 16, 16)
				if err != nil || low < 0xdc00 || low > 0xdfff {
					return fmt.Errorf("unpaired surrogate")
				}
				i += 6
			}
		}
	}
	return nil
}

func decode(raw []byte) (any, error) {
	if !utf8.Valid(raw) {
		return nil, fmt.Errorf("invalid UTF-8")
	}
	if err := surrogateCheck(raw); err != nil {
		return nil, err
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var read func(int) (any, error)
	read = func(depth int) (any, error) {
		if depth > 32 {
			return nil, fmt.Errorf("JSON nesting limit")
		}
		t, err := d.Token()
		if err != nil {
			return nil, err
		}
		switch v := t.(type) {
		case json.Delim:
			if v == '{' {
				out := Object{}
				for d.More() {
					key, err := d.Token()
					if err != nil {
						return nil, err
					}
					k, ok := key.(string)
					if !ok || !scalar(k) || has(out, k) {
						return nil, fmt.Errorf("invalid or duplicate key")
					}
					item, err := read(depth + 1)
					if err != nil {
						return nil, err
					}
					out[k] = item
				}
				end, err := d.Token()
				if err != nil || end != json.Delim('}') {
					return nil, fmt.Errorf("invalid object")
				}
				return out, nil
			}
			if v == '[' {
				out := []any{}
				for d.More() {
					item, err := read(depth + 1)
					if err != nil {
						return nil, err
					}
					out = append(out, item)
				}
				end, err := d.Token()
				if err != nil || end != json.Delim(']') {
					return nil, fmt.Errorf("invalid array")
				}
				return out, nil
			}
			return nil, fmt.Errorf("invalid delimiter")
		case json.Number:
			n, err := strconv.ParseInt(string(v), 10, 64)
			if err != nil || n < -maxInteger || n > maxInteger {
				return nil, fmt.Errorf("unsafe or noninteger number")
			}
			return n, nil
		case string:
			if !scalar(v) {
				return nil, fmt.Errorf("invalid scalar")
			}
			return v, nil
		default:
			return t, nil
		}
	}
	value, err := read(0)
	if err != nil {
		return nil, err
	}
	if _, err = d.Token(); err != io.EOF {
		return nil, fmt.Errorf("trailing JSON data")
	}
	return value, nil
}

func quoteJSON(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString("\\\"")
		case '\\':
			b.WriteString("\\\\")
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte('"')
	return b.String()
}

// canonical uses the same sorted-key, UTF-8 integer-only representation as the service.
func canonical(value any) ([]byte, error) {
	var b bytes.Buffer
	var write func(any, int) error
	write = func(v any, depth int) error {
		if depth > 32 {
			return fmt.Errorf("JSON nesting limit")
		}
		switch x := v.(type) {
		case nil:
			b.WriteString("null")
		case bool:
			b.WriteString(strconv.FormatBool(x))
		case string:
			if !scalar(x) {
				return fmt.Errorf("invalid scalar")
			}
			b.WriteString(quoteJSON(x))
		case int:
			return write(int64(x), depth)
		case int8:
			return write(int64(x), depth)
		case int16:
			return write(int64(x), depth)
		case int32:
			return write(int64(x), depth)
		case int64:
			if x < -maxInteger || x > maxInteger {
				return fmt.Errorf("unsafe integer")
			}
			b.WriteString(strconv.FormatInt(x, 10))
		case json.Number:
			n, err := strconv.ParseInt(string(x), 10, 64)
			if err != nil {
				return fmt.Errorf("unsupported JSON number")
			}
			return write(n, depth)
		case uint:
			if uint64(x) > uint64(maxInteger) {
				return fmt.Errorf("unsafe integer")
			}
			return write(int64(x), depth)
		case uint8:
			return write(int64(x), depth)
		case uint16:
			return write(int64(x), depth)
		case uint32:
			return write(int64(x), depth)
		case uint64:
			if x > uint64(maxInteger) {
				return fmt.Errorf("unsafe integer")
			}
			return write(int64(x), depth)
		case Object:
			keys := make([]string, 0, len(x))
			for k := range x {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			b.WriteByte('{')
			for i, k := range keys {
				if !scalar(k) {
					return fmt.Errorf("invalid key")
				}
				if i > 0 {
					b.WriteByte(',')
				}
				b.WriteString(quoteJSON(k))
				b.WriteByte(':')
				if err := write(x[k], depth+1); err != nil {
					return err
				}
			}
			b.WriteByte('}')
		default:
			rv := reflect.ValueOf(v)
			if rv.Kind() != reflect.Slice && rv.Kind() != reflect.Array {
				return fmt.Errorf("unsupported JSON value %T", v)
			}
			b.WriteByte('[')
			for i := 0; i < rv.Len(); i++ {
				if i > 0 {
					b.WriteByte(',')
				}
				if err := write(rv.Index(i).Interface(), depth+1); err != nil {
					return err
				}
			}
			b.WriteByte(']')
		}
		return nil
	}
	if err := write(value, 0); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

func snapshot(value Object) (Object, error) {
	raw, err := canonical(value)
	if err != nil {
		return nil, err
	}
	v, err := decode(raw)
	return object(v), err
}
func digest(value Object) string {
	raw, err := canonical(value)
	if err != nil {
		return ""
	}
	return fmt.Sprintf("sha256:%x", sha256.Sum256(raw))
}
