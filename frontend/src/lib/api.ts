/**
 * The application's API client singleton. Components and providers import `api` from here;
 * the client factory itself (src/lib/apiClient.ts) stays unit-testable with an injected base URL.
 */
import { createApiClient } from "./apiClient";

export const api = createApiClient();
