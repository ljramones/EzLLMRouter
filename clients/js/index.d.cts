import type { Wire02, Wire03, IntegrationV1, IntegrationV2, IntegrationV3 } from "./contracts.cjs";
export type { Wire02, Wire03, IntegrationV1, IntegrationV2, IntegrationV3 } from "./contracts.cjs";

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type JsonRecord = { [key: string]: JsonValue };
export type RetryGuidance = "never" | "query_first" | "orchestrator_decision";
export type IntegrationVersion = "1" | "2" | "3";
export type StatusSelector = { submission_id: string } | Wire02.WorkSelector;
export interface SubmitOptions { wait_ms?: number; }

export interface FetchBodyReader {
  read(): Promise<{ done: boolean; value?: Uint8Array }>;
  cancel(): Promise<void>;
  releaseLock(): void;
}

export interface FetchResponse {
  readonly status: number;
  readonly ok: boolean;
  readonly headers: { get(name: string): string | null };
  readonly body?: { getReader(): FetchBodyReader } | null;
  json(): Promise<unknown>;
  arrayBuffer(): Promise<ArrayBuffer>;
}
export interface FetchAbortSignal {
  readonly aborted: boolean;
  readonly reason: unknown;
  addEventListener(type: "abort", listener: () => void, options?: {once?: boolean}): void;
  removeEventListener(type: "abort", listener: () => void): void;
}
export type FetchSignal = typeof globalThis extends {AbortSignal: {prototype: infer S}} ? S : FetchAbortSignal;
export interface FetchRequest {
  method: string;
  headers: Record<string, string>;
  body?: string;
  redirect: "manual" | "error";
  cache?: "no-store";
  signal?: FetchSignal;
}
export type FetchImplementation = (url: string, options: FetchRequest) => Promise<FetchResponse>;
export interface ClientOptions { baseUrl: string; token: string; fetchImpl?: FetchImplementation; timeoutMs?: number | null; }
export interface ErrorDetails {
  selector?: StatusSelector;
  handle?: Wire02.SubmissionHandle | Wire03.Handle;
  work_key?: Wire02.WorkKey | Wire03.WorkKey;
  attempt_id?: string;
  failure_stage?: "before_transmit" | "after_transmit" | "before_send" | "after_send";
  error?: Wire02.Error | Wire03.ErrorResponse;
  cause?: unknown;
}
export declare class EzLLMRouterError extends Error implements ErrorDetails {
  constructor(code: string, httpStatus?: number | null, retryGuidance?: RetryGuidance,
    correlationId?: string | null, details?: ErrorDetails);
  readonly code: string;
  readonly http_status: number | null | undefined;
  readonly retry_guidance: RetryGuidance | undefined;
  readonly correlation_id: string | null | undefined;
  readonly selector?: StatusSelector;
  readonly handle?: Wire02.SubmissionHandle | Wire03.Handle;
  readonly work_key?: Wire02.WorkKey | Wire03.WorkKey;
  readonly attempt_id?: string;
  readonly failure_stage?: ErrorDetails["failure_stage"];
  readonly error?: Wire02.Error | Wire03.ErrorResponse;
  readonly cause?: unknown;
}

export type StartRun = {
  version: "1"; run_id: string; task_id: string; task_class: string; evaluation_ref: string;
} & (
  | { mode: "direct_human" }
  | { mode: "autonomous_agent"; agent_id: string; agent_version: string }
  | { mode: "user_delegated_agent"; agent_id: string; agent_version: string; initiating_user_id: string }
  | { mode: "nested_agent"; agent_id: string; agent_version: string; parent_run_id: string }
);
export interface AttributionRun {
  run_id: string; principal_id: string; charging_owner_id: string;
  initiating_user_id: string | null; agent_id: string | null; agent_version: string | null;
  parent_run_id: string | null; root_run_id: string; task_id: string; task_class: string;
  evaluation_ref: string; mode: StartRun["mode"]; created_at: string;
  status: "running" | "accepted" | "rejected" | "abandoned"; request_digest: string; terminal_at?: string;
}
export type OutcomeEvent = {
  version: "1"; event_id: string; run_id: string; subject_revision: number;
  evaluator_version: string; evidence_ref: string;
} & (
  | { kind: "task_outcome"; verdict: "accepted" | "rejected" | "abandoned" }
  | { kind: "step_evaluation"; verdict: "correct" | "incorrect" | "undetermined";
      step_id: string; step_revision: number; execution_generation: string }
);
export interface OutcomeReceipt {
  version: "1"; event_id: string; run_id: string; kind: OutcomeEvent["kind"];
  subject_revision: number; recorded_at: string; event_digest: string;
}

export declare class EzLLMRouterClient {
  constructor(options: ClientOptions);
  submit(request: Wire02.SubmitRequest, options?: SubmitOptions): Promise<Wire02.SubmitReply>;
  submitInRun(request: Wire02.SubmitRequest, runId: string, options?: SubmitOptions): Promise<Wire02.SubmitReply>;
  getStatus(selector: StatusSelector, options?: { contractVersion?: "0.2" }): Promise<Wire02.StatusSnapshot>;
  getStatus(selector: Wire03.StatusQuery, options: { contractVersion: "0.3" }): Promise<Wire03.StatusSnapshot>;
  getCapabilities(): Promise<Wire02.CapabilityResponse>;
  startRun(run: StartRun): Promise<AttributionRun>;
  getRun(runId: string): Promise<AttributionRun>;
  reportOutcome(event: OutcomeEvent): Promise<OutcomeReceipt>;
  getOutcomeReceipt(eventId: string): Promise<OutcomeReceipt>;
  submit_embedding(request: Wire03.SubmitEmbedding, options?: SubmitOptions): Promise<Wire03.SubmitReply>;
  submit_rerank(request: Wire03.SubmitRerank, options?: SubmitOptions): Promise<Wire03.SubmitReply>;
  submitEmbedding(request: Wire03.SubmitEmbedding, options?: SubmitOptions): Promise<Wire03.SubmitReply>;
  submitRerank(request: Wire03.SubmitRerank, options?: SubmitOptions): Promise<Wire03.SubmitReply>;
  getSuccessorStatus(selector: Wire03.StatusQuery): Promise<Wire03.StatusSnapshot>;
}

export type AccountingEvent<V extends IntegrationVersion> = V extends "1" ? IntegrationV1.event : V extends "2" ? IntegrationV2.event : IntegrationV3.event;
export type Dataset<V extends IntegrationVersion> = V extends "1" ? IntegrationV1.dataset : V extends "2" ? IntegrationV2.dataset : IntegrationV3.dataset;
export type Account<V extends IntegrationVersion> = V extends "1" ? IntegrationV1.account : V extends "2" ? IntegrationV2.account : IntegrationV3.account;
export type AccountState<V extends IntegrationVersion> = V extends "1" ? IntegrationV1.account_state : V extends "2" ? IntegrationV2.account_state : IntegrationV3.account_state;
export type Snapshot<V extends "2" | "3"> = V extends "2" ? IntegrationV2.snapshot : IntegrationV3.snapshot;
export interface IntegrationReceipt<V extends IntegrationVersion> {
  integration_version: V; dataset_id: string; event_id: string; kind: AccountingEvent<V>["kind"];
  event_digest: string; membership_at_receipt: "included" | "excluded_before_activation" | "pending_start";
  [key: string]: unknown;
}
export interface Eligibility<V extends IntegrationVersion> {
  integration_version: V; dataset_id: string; account_id: string; model_id?: string;
  account_revision: number; usable: boolean;
  reason: "usable" | "account_disabled" | "model_not_permitted" | "operation_not_permitted";
  eligibility_id?: string; evaluated_at?: string; eligibility_digest?: string;
  [key: string]: unknown;
}
export type OperationSelector = {
  operation_family: IntegrationV3.operation_family; capability: string;
} & (
  | { selection_kind: "known_model"; model_id: string }
  | { selection_kind: "provider_selected" | "not_applicable"; model_id?: never }
);
export interface IntegrationOptions<V extends IntegrationVersion> { version?: V; fetchImpl?: FetchImplementation; timeoutMs?: number | null; }
export declare class IntegrationClientError extends Error {
  constructor(code: string, httpStatus?: number | null, retryGuidance?: RetryGuidance);
  readonly code: string;
  readonly http_status: number | null;
  readonly httpStatus: number | null;
  readonly retry_guidance: RetryGuidance;
  readonly retryGuidance: RetryGuidance;
}
export declare class IntegrationClient<V extends IntegrationVersion = "1"> {
  constructor(baseUrl: string, token: string, options?: IntegrationOptions<V>);
  readonly version: V;
  createDataset(body: Dataset<V>): Promise<JsonRecord>;
  registerAccount(body: Account<V>): Promise<JsonRecord>;
  setAccountState(accountId: string, body: AccountState<V>): Promise<JsonRecord>;
  setAccountPermissions(accountId: V extends "3" ? string : never, body: IntegrationV3.account_permissions): Promise<JsonRecord>;
  submitObservation(event: AccountingEvent<V>): Promise<IntegrationReceipt<V>>;
  recoverReceipt(datasetId: string, eventId: string): Promise<IntegrationReceipt<V>>;
  eligibility(datasetId: string, accountId: string, modelId: string): Promise<Eligibility<V>>;
  operationEligibility(datasetId: V extends "3" ? string : never, accountId: string, selector: OperationSelector): Promise<Eligibility<"3">>;
  report(datasetId: string): Promise<JsonRecord>;
  submitSnapshot(snapshot: Snapshot<Extract<V, "2" | "3">>): Promise<JsonRecord>;
  snapshot(datasetId: V extends "1" ? never : string, snapshotId: string): Promise<JsonRecord>;
  exportDataset(datasetId: V extends "1" ? never : string): Promise<JsonRecord>;
}
export declare const contractVersion: "0.2";
