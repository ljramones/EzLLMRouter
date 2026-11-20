package ezllmrouter

import (
	"embed"
	"encoding/json"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

//go:embed schemas/*.json
var schemaFiles embed.FS
var schemas = loadSchemas()
var idPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$`)
var hashPattern = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
var unicodePattern = regexp.MustCompile(`\\u([0-9a-fA-F]{4})`)
var patterns sync.Map

func loadSchemas() map[string]Object {
	out := map[string]Object{}
	for key, file := range map[string]string{"0.2": "wire02.json", "0.3": "dev12_schemas.json", "1": "integration_schema.json", "2": "integration_schema_v2.json", "3": "integration_schema_v3.json"} {
		raw, err := schemaFiles.ReadFile("schemas/" + file)
		if err != nil {
			panic(err)
		}
		var bundle Object
		if err = json.Unmarshal(raw, &bundle); err != nil {
			panic(err)
		}
		out[key] = field(bundle, "$defs")
	}
	return out
}
func identifier(v any) bool { s, ok := v.(string); return ok && idPattern.MatchString(s) }
func positive(v any) bool   { n, ok := v.(int64); return ok && n > 0 && n <= maxInteger }
func utc(v any) bool {
	s, ok := v.(string)
	if !ok || len(s) != 20 || s[:4] == "0000" {
		return false
	}
	_, err := time.Parse("2006-01-02T15:04:05Z", s)
	return err == nil
}
func schemaNumber(v any, defaultValue int64) int64 {
	switch n := v.(type) {
	case float64:
		return int64(n)
	case int64:
		return n
	}
	return defaultValue
}
func schemaEqual(a, b any) bool {
	if n, ok := b.(float64); ok {
		return equal(a, int64(n))
	}
	return equal(a, b)
}
func matches(v any, shape Object, defs Object) bool {
	if ref := str(shape["$ref"]); ref != "" {
		name := strings.TrimPrefix(ref, "#/$defs/")
		if name == ref || !has(defs, name) {
			return false
		}
		if name == "PublicText" && strings.ContainsFunc(str(v), func(r rune) bool { return r < 32 || r == 127 }) {
			return false
		}
		if (name == "utc" || name == "UtcSecond") && !utc(v) {
			return false
		}
		return matches(v, field(defs, name), defs)
	}
	for _, part := range array(shape["allOf"]) {
		if !matches(v, object(part), defs) {
			return false
		}
	}
	if parts, ok := shape["anyOf"]; ok {
		found := false
		for _, p := range array(parts) {
			found = found || matches(v, object(p), defs)
		}
		if !found {
			return false
		}
	}
	if parts, ok := shape["oneOf"]; ok {
		count := 0
		for _, p := range array(parts) {
			if matches(v, object(p), defs) {
				count++
			}
		}
		if count != 1 {
			return false
		}
	}
	if part, ok := shape["not"]; ok && matches(v, object(part), defs) {
		return false
	}
	if cond, ok := shape["if"]; ok {
		branch := "else"
		if matches(v, object(cond), defs) {
			branch = "then"
		}
		if p, ok := shape[branch]; ok && !matches(v, object(p), defs) {
			return false
		}
	}
	if c, ok := shape["const"]; ok && !schemaEqual(v, c) {
		return false
	}
	if values, ok := shape["enum"]; ok {
		found := false
		for _, x := range array(values) {
			found = found || schemaEqual(v, x)
		}
		if !found {
			return false
		}
	}
	if m, ok := v.(Object); ok {
		props := field(shape, "properties")
		for _, key := range array(shape["required"]) {
			if !has(m, str(key)) {
				return false
			}
		}
		for key, item := range m {
			if p, ok := props[key]; ok {
				if !matches(item, object(p), defs) {
					return false
				}
			} else if has(shape, "additionalProperties") {
				if shape["additionalProperties"] == false {
					return false
				}
				if p, ok := shape["additionalProperties"].(Object); ok && !matches(item, p, defs) {
					return false
				}
			}
		}
	} else if has(shape, "required") { /* JSON Schema object keywords apply only to objects. */
	}
	switch str(shape["type"]) {
	case "object":
		return object(v) != nil
	case "array":
		a, ok := v.([]any)
		if !ok || int64(len(a)) < schemaNumber(shape["minItems"], 0) || int64(len(a)) > schemaNumber(shape["maxItems"], maxInteger) {
			return false
		}
		seen := map[string]bool{}
		for _, item := range a {
			if p, ok := shape["items"]; ok && !matches(item, object(p), defs) {
				return false
			}
			if shape["uniqueItems"] == true {
				raw, err := canonical(item)
				if err != nil || seen[string(raw)] {
					return false
				}
				seen[string(raw)] = true
			}
		}
		return true
	case "string":
		s, ok := v.(string)
		if !ok || !scalar(s) || int64(utf8.RuneCountInString(s)) < schemaNumber(shape["minLength"], 0) || int64(utf8.RuneCountInString(s)) > schemaNumber(shape["maxLength"], maxInteger) {
			return false
		}
		if pattern, ok := shape["pattern"].(string); ok {
			pattern = strings.ReplaceAll(pattern, `(?![\s\S])`, `$`)
			pattern = unicodePattern.ReplaceAllString(pattern, `\x{$1}`)
			cached, ok := patterns.Load(pattern)
			if !ok {
				rx, err := regexp.Compile(pattern)
				if err != nil {
					return false
				}
				cached, _ = patterns.LoadOrStore(pattern, rx)
			}
			if !cached.(*regexp.Regexp).MatchString(s) {
				return false
			}
		}
		return true
	case "integer":
		n, ok := v.(int64)
		return ok && n >= schemaNumber(shape["minimum"], -maxInteger) && n <= schemaNumber(shape["maximum"], maxInteger)
	case "boolean":
		_, ok := v.(bool)
		return ok
	case "null":
		return v == nil
	}
	return true
}
func valuePolicy(value any, nulls, controls bool) bool {
	switch v := value.(type) {
	case nil:
		return nulls
	case string:
		return !controls || !strings.ContainsFunc(v, func(r rune) bool { return r < 32 || r == 127 })
	case Object:
		for key, item := range v {
			if !valuePolicy(key, nulls, controls) || !valuePolicy(item, nulls, controls) {
				return false
			}
		}
	case []any:
		for _, item := range v {
			if !valuePolicy(item, nulls, controls) {
				return false
			}
		}
	}
	return true
}

func named(v any, version, name string) bool {
	defs := schemas[version]
	return (version != "0.3" || valuePolicy(v, true, true)) && has(defs, name) && matches(v, field(defs, name), defs)
}
func selected(request Object) Object {
	out := Object{}
	for _, k := range selectorKeys {
		out[k] = request[k]
	}
	return out
}

var selectorKeys = []string{"task_id", "step_id", "step_revision", "execution_generation"}

func matchingHandle(v Object, selector Object, version string) Object {
	h := field(v, "handle")
	name := "SubmissionHandle"
	if version == "0.3" {
		name = "Handle"
	}
	if selector == nil || !named(h, version, name) {
		return nil
	}
	if has(selector, "submission_id") {
		if h["submission_id"] != selector["submission_id"] {
			return nil
		}
	} else {
		for _, k := range selectorKeys {
			if !equal(field(h, "work_key")[k], selector[k]) {
				return nil
			}
		}
	}
	return h
}
