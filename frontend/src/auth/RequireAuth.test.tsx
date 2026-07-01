import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { AuthContext, type AuthContextValue } from "./AuthContext";
import { RequireAuth } from "./RequireAuth";

function renderGuard(overrides: Partial<AuthContextValue>) {
  const value: AuthContextValue = {
    status: "authorized",
    user: null,
    email: "analyst@example.com",
    error: null,
    signInError: null,
    signIn: async () => {},
    signOut: async () => {},
    retry: () => {},
    ...overrides,
  };
  return render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/signin" element={<div>SIGN IN SCREEN</div>} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<div>PROTECTED CONTENT</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("RequireAuth", () => {
  it("renders the protected route when authorized", () => {
    renderGuard({ status: "authorized" });
    expect(screen.getByText("PROTECTED CONTENT")).toBeInTheDocument();
  });

  it("redirects to sign-in when signed out", () => {
    renderGuard({ status: "signed-out" });
    expect(screen.getByText("SIGN IN SCREEN")).toBeInTheDocument();
    expect(screen.queryByText("PROTECTED CONTENT")).not.toBeInTheDocument();
  });

  it("shows a clear not-authorized notice on a 403 (forbidden)", () => {
    renderGuard({ status: "forbidden", email: "outsider@example.com" });
    expect(screen.getByText("Not authorized")).toBeInTheDocument();
    expect(screen.getByText(/not on the analyst allowlist/i)).toBeInTheDocument();
    expect(screen.queryByText("PROTECTED CONTENT")).not.toBeInTheDocument();
  });

  it("shows a loader while verifying access", () => {
    renderGuard({ status: "verifying" });
    expect(screen.getByText("Verifying access…")).toBeInTheDocument();
  });
});
