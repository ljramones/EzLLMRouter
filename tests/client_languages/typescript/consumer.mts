import {
  EzLLMRouterClient, IntegrationClient, EzLLMRouterError, IntegrationClientError,
  contractVersion,
} from "@cognitivedynamics/ezllmrouter-client";
import type { Wire02, Wire03, IntegrationV1, IntegrationV2, IntegrationV3, FetchImplementation } from "@cognitivedynamics/ezllmrouter-client";

const version: "0.2" = contractVersion;
const injected: FetchImplementation = async () => ({
  status: 200, ok: true, headers: { get: () => "0.2" },
  json: async () => ({}), arrayBuffer: async () => new ArrayBuffer(0),
});
const client = new EzLLMRouterClient({ baseUrl: "http://synthetic.invalid", token: "synthetic-token", fetchImpl: injected });
const capabilities: Promise<Wire02.CapabilityResponse> = client.getCapabilities();
const status: Promise<Wire02.StatusSnapshot> = client.getStatus({ submission_id: "submission.synthetic" });
const successor: Promise<Wire03.StatusSnapshot> = client.getStatus({ submission_id: "submission.synthetic" }, { contractVersion: "0.3" });
declare const embedding: Wire03.SubmitEmbedding;
declare const rerank: Wire03.SubmitRerank;
client.submitEmbedding(embedding, { wait_ms: 0 }); client.submitRerank(rerank);
client.submit_embedding(embedding); client.submit_rerank(rerank);
// @ts-expect-error embedding and rerank requests have different operations and inputs
client.submitEmbedding(rerank);
// @ts-expect-error wait times use numbers
client.submitRerank(rerank, { wait_ms: "0" });
// @ts-expect-error selector requires a submission ID or a complete work key
client.getStatus({ task_id: "task.incomplete" });

declare const event1: IntegrationV1.event;
declare const event2: IntegrationV2.event;
declare const event3: IntegrationV3.event;
declare const snapshot2: IntegrationV2.snapshot;
declare const permissions: IntegrationV3.account_permissions;
const one = new IntegrationClient("http://synthetic.invalid", "synthetic-token");
const two = new IntegrationClient("http://synthetic.invalid", "synthetic-token", { version: "2" });
const three = new IntegrationClient("http://synthetic.invalid", "synthetic-token", { version: "3" });
one.submitObservation(event1); two.submitObservation(event2); three.submitObservation(event3);
two.submitSnapshot(snapshot2); two.exportDataset("dataset.synthetic");
three.setAccountPermissions("account.synthetic", permissions);
three.operationEligibility("dataset.synthetic", "account.synthetic", { operation_family: "speech_input", capability: "transcription", selection_kind: "provider_selected" });
// @ts-expect-error v2 observations cannot be submitted through v1
one.submitObservation(event2);
// @ts-expect-error v1 has no snapshots
one.submitSnapshot(snapshot2);
// @ts-expect-error account permissions require v3
two.setAccountPermissions("account.synthetic", permissions);
// @ts-expect-error known model selection requires its model ID
three.operationEligibility("dataset.synthetic", "account.synthetic", { operation_family: "generation", capability: "generation", selection_kind: "known_model" });
client.startRun({ version: "1", run_id: "run.synthetic", task_id: "task.synthetic", task_class: "class.synthetic", evaluation_ref: "rubric.v1", mode: "autonomous_agent", agent_id: "agent.synthetic", agent_version: "1" });
// @ts-expect-error autonomous runs require an agent identity
client.startRun({ version: "1", run_id: "run.synthetic", task_id: "task.synthetic", task_class: "class.synthetic", evaluation_ref: "rubric.v1", mode: "autonomous_agent" });
const executionError = new EzLLMRouterError("TRANSPORT_OUTCOME_UNKNOWN", null, "query_first");
const accountingError = new IntegrationClientError("PROTOCOL_INVALID", 200, "query_first");
const executionStatus: number | null | undefined = executionError.http_status;
const accountingStatus: number | null = accountingError.httpStatus;
void [version, capabilities, status, successor, executionStatus, accountingStatus];
