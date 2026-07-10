import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./apiClient";
import { parseSseBlock, streamInquiry } from "./inquiryStream";
import type { StreamEvent } from "../types/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Build a streamed `text/event-stream` Response whose body emits the given raw chunks in order. */
function sseResponse(chunks: string[], init?: ResponseInit): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    ...init,
  });
}

async function collect(gen: AsyncGenerator<StreamEvent>): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of gen) events.push(event);
  return events;
}

describe("parseSseBlock", () => {
  it("parses an event block into a tagged StreamEvent (name lifted to `type`)", () => {
    const event = parseSseBlock(
      'event: run_started\ndata: {"trace_id":"t1","vendor_id":"V-001","model":"m"}',
    );
    expect(event).toEqual({ type: "run_started", trace_id: "t1", vendor_id: "V-001", model: "m" });
  });

  it("parses a stage_completed block with its summary", () => {
    const event = parseSseBlock(
      'event: stage_completed\ndata: {"stage":"lookup","summary":{"count":2,"shipment_ids":["S-1"]}}',
    );
    expect(event).toEqual({
      type: "stage_completed",
      stage: "lookup",
      summary: { count: 2, shipment_ids: ["S-1"] },
    });
  });

  it("parses the Layer-2 thinking_delta and text_delta blocks", () => {
    expect(parseSseBlock('event: thinking_delta\ndata: {"text":"Let me check."}')).toEqual({
      type: "thinking_delta",
      text: "Let me check.",
    });
    expect(parseSseBlock('event: text_delta\ndata: {"text":"The shipment is held."}')).toEqual({
      type: "text_delta",
      text: "The shipment is held.",
    });
  });

  it("ignores comment/heartbeat and unknown-event blocks", () => {
    expect(parseSseBlock(": keep-alive")).toBeNull();
    expect(parseSseBlock('event: bogus\ndata: {"x":1}')).toBeNull();
  });
});

describe("streamInquiry", () => {
  it("reassembles events split across chunk boundaries", async () => {
    const frames =
      'event: run_started\ndata: {"trace_id":"t1","vendor_id":"V-001","model":"m"}\n\n' +
      'event: stage_started\ndata: {"stage":"classify"}\n\n' +
      'event: done\ndata: {"result":{"trace_id":"t1","disposition":"draft"}}\n\n';
    // Split at arbitrary points, including mid-frame, to exercise the buffer.
    const chunks = [frames.slice(0, 20), frames.slice(20, 90), frames.slice(90)];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(chunks)));

    const events = await collect(
      streamInquiry({ vendorId: "V-001", inquiry: "hi", baseUrl: "/api" }),
    );

    expect(events.map((e) => e.type)).toEqual(["run_started", "stage_started", "done"]);
    expect(events[2]).toMatchObject({ type: "done", result: { trace_id: "t1" } });
  });

  it("posts to the streaming endpoint with the JSON body and no auth header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(["event: done\ndata: {\"result\":{}}\n\n"]));
    vi.stubGlobal("fetch", fetchMock);

    await collect(streamInquiry({ vendorId: "V-001", inquiry: "why held?", baseUrl: "/api" }));

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/inquiry/stream");
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    // Public demo: no auth, so no Authorization header is ever attached.
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.get("Accept")).toBe("text/event-stream");
    expect(init.body).toBe(JSON.stringify({ vendor_id: "V-001", inquiry: "why held?" }));
  });

  it("throws an ApiError when the pre-stream response is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Unknown vendor: V-404" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const error = await collect(
      streamInquiry({ vendorId: "V-404", inquiry: "x", baseUrl: "/api" }),
    ).then(
      () => null,
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(ApiError);
    if (error instanceof ApiError) {
      expect(error.status).toBe(404);
      expect(error.detail).toBe("Unknown vendor: V-404");
    }
  });
});
