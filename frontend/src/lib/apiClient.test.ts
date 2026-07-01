import { describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient } from "./apiClient";
import type { AgentResult, Vendor } from "../types/api";

type FetchArgs = [input: string | URL | Request, init?: RequestInit];

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const VENDOR: Vendor = {
  vendor_id: "V-001",
  legal_name: "Meridian Components LLC",
  country: "Taiwan",
  customs_broker: "Pacific Rim Customs Brokerage",
  categories: ["electronics"],
  active: true,
};

describe("createApiClient", () => {
  it("targets the same-origin base and attaches the bearer + Accept headers on a GET", async () => {
    const fetchMock = stubFetch(jsonResponse([VENDOR]));
    const client = createApiClient(async () => "tok-123", "/api");

    const vendors = await client.listVendors();

    expect(vendors).toEqual([VENDOR]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/vendors");
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok-123");
    expect(headers.get("Accept")).toBe("application/json");
    // A GET has no body, so no Content-Type is set.
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("omits the Authorization header when no user is signed in", async () => {
    const fetchMock = stubFetch(jsonResponse([]));
    const client = createApiClient(async () => null, "/api");

    await client.listVendors();

    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).has("Authorization")).toBe(false);
  });

  it("POSTs an inquiry with a JSON body + Content-Type and returns the parsed result", async () => {
    const result: Partial<AgentResult> = { trace_id: "tr-abc", disposition: "draft" };
    const fetchMock = stubFetch(jsonResponse(result));
    const client = createApiClient(async () => "tok", "/api");

    const returned = await client.submitInquiry({ vendor_id: "V-001", inquiry: "why held?" });

    expect(returned).toEqual(result);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/inquiry");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(init?.body).toBe(JSON.stringify({ vendor_id: "V-001", inquiry: "why held?" }));
  });

  it("posts the disposition decision to the url-encoded trace path", async () => {
    const fetchMock = stubFetch(jsonResponse({ trace_id: "tr-1", disposition: "approved" }));
    const client = createApiClient(async () => "tok", "/api");

    await client.setDisposition("tr-1", "approved");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/traces/tr-1/disposition");
    expect(init?.body).toBe(JSON.stringify({ disposition: "approved" }));
  });

  it("throws an ApiError carrying the status and FastAPI detail on a 403", async () => {
    stubFetch(jsonResponse({ detail: "Not authorized for the requested vendor scope." }, { status: 403 }));
    const client = createApiClient(async () => "tok", "/api");

    const error = await client.getIdentity().then(
      () => null,
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(ApiError);
    if (error instanceof ApiError) {
      expect(error.status).toBe(403);
      expect(error.isForbidden).toBe(true);
      expect(error.detail).toBe("Not authorized for the requested vendor scope.");
    }
  });

  it("still throws an ApiError when the error body is not JSON", async () => {
    stubFetch(new Response("<html>502</html>", { status: 502 }));
    const client = createApiClient(async () => "tok", "/api");

    const error = await client.listTraces().then(
      () => null,
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(ApiError);
    if (error instanceof ApiError) {
      expect(error.status).toBe(502);
      expect(error.detail).toBeNull();
      expect(error.message).toContain("502");
    }
  });
});
