/**
 * SSE client for the agent pipeline: POST /api/inquiry/stream, streamed as it runs.
 *
 * The browser consumes the stream with `fetch` + a `ReadableStream` reader (NOT `EventSource`) so the
 * Firebase Bearer token can ride in the Authorization header (docs/FRONTEND_PLAN.md "Transport
 * notes"). Frames are `event: <name>\ndata: <json>\n\n` blocks; `parseSseBlock` turns one block into a
 * `StreamEvent` (the `type` tag = the SSE event name; the JSON never carries the name), and
 * `streamInquiry` buffers raw bytes into complete blocks and yields them. The vocabulary is the
 * Layer-1 pipeline-progress events plus the Layer-2 model-output deltas (`thinking_delta` /
 * `text_delta`). Same-origin `/api`, same as the JSON client - Vite proxy in dev, Hosting rewrite in
 * prod.
 */
import { config } from "../config";
import { type TokenProvider, toApiError } from "./apiClient";
import type { StreamEvent } from "../types/api";

/** The SSE `event:` names the backend emits (src/streaming.py). An unknown name is ignored. */
const KNOWN_EVENTS: ReadonlySet<string> = new Set([
  "run_started",
  "stage_started",
  "stage_completed",
  "thinking_delta",
  "text_delta",
  "guard_triggered",
  "done",
  "error",
]);

export interface StreamInquiryOptions {
  vendorId: string;
  inquiry: string;
  /** Resolves the current Firebase ID token (injected, so this module stays SDK-agnostic). */
  getToken: TokenProvider;
  /** Aborts the in-flight fetch when the run is superseded or the component unmounts. */
  signal?: AbortSignal;
  baseUrl?: string;
}

/**
 * Parse one SSE block (the text between blank-line separators) into a `StreamEvent`, or null when the
 * block is a comment/heartbeat, has no recognized event name, or carries no data. Multiple `data:`
 * lines are joined with newlines per the SSE spec; the JSON is spread under the `type` discriminant.
 */
export function parseSseBlock(block: string): StreamEvent | null {
  let name: string | null = null;
  const dataLines: string[] = [];

  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line === "" || line.startsWith(":")) continue; // blank / comment (heartbeat)
    if (line.startsWith("event:")) {
      name = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      // Strip the field name and a single optional leading space (SSE spec).
      dataLines.push(line.slice("data:".length).replace(/^ /, ""));
    }
  }

  if (name === null || !KNOWN_EVENTS.has(name) || dataLines.length === 0) return null;
  const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
  // The backend keeps the event name off the JSON payload; the union is discriminated by `type`.
  return { type: name, ...data } as StreamEvent;
}

/**
 * Run one inquiry against the streaming endpoint, yielding pipeline events as they arrive.
 *
 * Throws an `ApiError` if the pre-stream response is not ok (a 403 scope refusal, a 401, a 422 - the
 * gate runs before the stream opens). Once streaming, backend-side failures surface as terminal
 * `error` events in the stream, not exceptions. An aborted signal rejects the underlying read; the
 * caller distinguishes that from a real failure via `signal.aborted`.
 */
export async function* streamInquiry({
  vendorId,
  inquiry,
  getToken,
  signal,
  baseUrl = config.apiBaseUrl,
}: StreamInquiryOptions): AsyncGenerator<StreamEvent> {
  const headers = new Headers({
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  });
  const token = await getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${baseUrl}/inquiry/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify({ vendor_id: vendorId, inquiry }),
    signal,
  });

  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new Error("The streaming response has no body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let separator = buffer.indexOf("\n\n");
      while (separator !== -1) {
        const block = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        const event = parseSseBlock(block);
        if (event) yield event;
        separator = buffer.indexOf("\n\n");
      }
    }
    // Flush any trailing block not terminated by a blank line (defensive; the backend always sends one).
    buffer += decoder.decode();
    const tail = buffer.trim();
    if (tail) {
      const event = parseSseBlock(tail);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
