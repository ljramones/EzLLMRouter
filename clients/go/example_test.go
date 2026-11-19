package ezllmrouter_test

import (
	"fmt"

	ezllmrouter "github.com/ljramones/EzLLMRouter/clients/go"
)

func ExampleParseObject() {
	record, err := ezllmrouter.ParseObject([]byte(`{"integration_version":"3","revision":1,"amount_decimal":"0.001"}`))
	if err != nil {
		panic(err)
	}
	fmt.Printf("%T %s\n", record["revision"], record["amount_decimal"])
	// Output: int64 0.001
}
