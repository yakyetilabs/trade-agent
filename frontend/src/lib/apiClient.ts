/**
 * Typed, same-origin API client for the trade-agent backend.
 *
 * Every request targets the same-origin `/api` base (Vite proxy in dev, Firebase Hosting rewrite in
 * prod - no CORS on either path) and carries the caller's Firebase ID token as
 * `Authorization: Bearer <token>`. The token is supplied by an injected async provider rather than
 * imported from Firebase, so this module is decoupled and unit-testable without the SDK;
 * src/lib/api.ts binds the real provider from the signed-in user.
 */
import { config } from "../config";
import type {
  AgentResult,
  AgentTrace,
  DispositionDecision,
  DispositionResponse,
  IdentityResponse,
  InquiryRequest,
  Vendor,
} from "../types/api";

/** Resolves the current Firebase ID token, or null when no user is signed in. */
export type TokenProvider = () => Promise<string | null>;

/** A non-2xx backend response. `status` drives UI branching (403 -> not-authorized state); `detail`
 *  is FastAPI's `{ "detail": ... }` message when present. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;

  constructor(status: number, message: string, detail: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

export interface ApiClient {
  /** GET /api/me - resolves the verified analyst identity (used to confirm authorization). */
  getIdentity(): Promise<IdentityResponse>;
  /** GET /api/vendors - the analyst's authorized vendors (the scope picker). */
  listVendors(): Promise<Vendor[]>;
  /** GET /api/traces - recent audit traces in scope, newest first. */
  listTraces(): Promise<AgentTrace[]>;
  /** POST /api/inquiry - run the pipeline synchronously (non-streaming path / fallback). */
  submitInquiry(request: InquiryRequest): Promise<AgentResult>;
  /** POST /api/traces/{id}/disposition - record a human approve/reject decision. */
  setDisposition(traceId: string, decision: DispositionDecision): Promise<DispositionResponse>;
}

/** Map a non-2xx `Response` to an `ApiError`, surfacing FastAPI's `{ detail }` when present.
 *  Exported so the streaming client (src/lib/inquiryStream.ts) reports pre-stream failures - a 403
 *  scope refusal, a 401, a 422 - through the same error type the JSON client uses. */
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

/**
 * Build an API client bound to a token provider and base URL. The base defaults to the same-origin
 * `/api` from config; the token provider is injected so tests (and the real Firebase binding) can
 * substitute their own.
 */
export function createApiClient(
  getToken: TokenProvider,
  baseUrl: string = config.apiBaseUrl,
): ApiClient {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    headers.set("Accept", "application/json");
    if (init?.body !== undefined) headers.set("Content-Type", "application/json");

    const token = await getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
    if (!response.ok) throw await toApiError(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  return {
    getIdentity: () => request<IdentityResponse>("/me"),
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
