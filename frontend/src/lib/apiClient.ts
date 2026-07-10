/**
 * Typed API client for the trade-agent backend.
 *
 * Every request targets the configured API base: same-origin `/api` in dev (the Vite proxy
 * forwards it to the local backend), the split-origin `api.` subdomain in prod (a cross-origin
 * call the backend CORS-allowlists). The API is a public demo - no auth header, no token.
 */
import { config } from "../config";
import type {
  AgentResult,
  AgentTrace,
  DispositionDecision,
  DispositionResponse,
  InquiryRequest,
  Vendor,
} from "../types/api";

/** A non-2xx backend response. `status` drives UI branching; `detail` is FastAPI's
 *  `{ "detail": ... }` message when present. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;

  constructor(status: number, message: string, detail: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface ApiClient {
  /** GET /api/vendors - all vendors (the scope picker). */
  listVendors(): Promise<Vendor[]>;
  /** GET /api/traces - recent audit traces, newest first. */
  listTraces(): Promise<AgentTrace[]>;
  /** POST /api/inquiry - run the pipeline synchronously (non-streaming path / fallback). */
  submitInquiry(request: InquiryRequest): Promise<AgentResult>;
  /** POST /api/traces/{id}/disposition - record a human approve/reject decision. */
  setDisposition(traceId: string, decision: DispositionDecision): Promise<DispositionResponse>;
}

/** Map a non-2xx `Response` to an `ApiError`, surfacing FastAPI's `{ detail }` when present.
 *  Exported so the streaming client (src/lib/inquiryStream.ts) reports pre-stream failures - a
 *  404, a 422 - through the same error type the JSON client uses. */
export async function toApiError(response: Response): Promise<ApiError> {
  let detail: string | null = null;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const raw = (body as { detail: unknown }).detail;
      if (typeof raw === "string") detail = raw;
    }
  } catch {
    // Non-JSON error body (e.g. an upstream proxy error page) - fall back to a status message.
  }
  return new ApiError(response.status, detail ?? `Request failed (HTTP ${response.status})`, detail);
}

/** Build an API client. The base defaults to the configured API base URL; tests substitute
 *  their own. */
export function createApiClient(baseUrl: string = config.apiBaseUrl): ApiClient {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    headers.set("Accept", "application/json");
    if (init?.body !== undefined) headers.set("Content-Type", "application/json");

    const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
    if (!response.ok) throw await toApiError(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  return {
    listVendors: () => request<Vendor[]>("/vendors"),
    listTraces: () => request<AgentTrace[]>("/traces"),
    submitInquiry: (inquiry) =>
      request<AgentResult>("/inquiry", { method: "POST", body: JSON.stringify(inquiry) }),
    setDisposition: (traceId, decision) =>
      request<DispositionResponse>(`/traces/${encodeURIComponent(traceId)}/disposition`, {
        method: "POST",
        body: JSON.stringify({ disposition: decision }),
      }),
  };
}
