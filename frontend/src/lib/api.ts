/**
 * The application's API client singleton - the API surface bound to the real Firebase token source.
 *
 * Components and providers import `api` from here. The client itself (src/lib/apiClient.ts) stays
 * Firebase-agnostic and unit-testable; this module is the one place the two are wired together.
 */
import { createApiClient } from "./apiClient";
import { getFirebaseIdToken } from "./firebase";

export const api = createApiClient(getFirebaseIdToken);
