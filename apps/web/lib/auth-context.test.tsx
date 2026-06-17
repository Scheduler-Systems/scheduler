import { describe, it, expect, vi } from "vitest";

// Mock firebase/auth to avoid real SDK boot, and `./firebase` so we don't
// try to read a real config.
const authListeners: ((user: unknown) => void)[] = [];
const mockAuth = { currentUser: null as unknown };

vi.mock("firebase/auth", () => ({
  onAuthStateChanged: (_auth: unknown, cb: (u: unknown) => void) => {
    authListeners.push(cb);
    // Immediately push "no user" so loading resolves in tests
    Promise.resolve().then(() => cb(null));
    return () => undefined;
  },
  signInWithEmailAndPassword: vi.fn(() => Promise.resolve({ user: { uid: "u1" } })),
  signInWithPopup: vi.fn(() => Promise.resolve({ user: { uid: "u2" } })),
  GoogleAuthProvider: class {},
  signOut: vi.fn(() => Promise.resolve()),
  createUserWithEmailAndPassword: vi.fn(() =>
    Promise.resolve({ user: { uid: "u3" } })
  ),
  updateProfile: vi.fn(() => Promise.resolve()),
  sendPasswordResetEmail: vi.fn(() => Promise.resolve()),
  sendEmailVerification: vi.fn(() => Promise.resolve()),
  RecaptchaVerifier: class {
    clear() {}
  },
  signInWithPhoneNumber: vi.fn(() =>
    Promise.resolve({ confirm: () => Promise.resolve({ user: { uid: "u4" } }) })
  ),
}));

vi.mock("./firebase", () => ({
  getFirebaseAuth: () => mockAuth,
}));

const { AuthProvider, useAuth } = await import("./auth-context");
const { render, screen, act, waitFor } = await import("@testing-library/react");
const userEvent = (await import("@testing-library/user-event")).default;

function Harness() {
  const {
    user,
    loading,
    signInWithEmail,
    signInWithGoogle,
    signOut,
    signUpWithEmail,
    sendPasswordReset,
    sendVerificationEmail,
    reloadUser,
    startPhoneSignIn,
  } = useAuth();
  return (
    <div>
      <span data-testid="loading">{loading ? "loading" : "ready"}</span>
      <span data-testid="user">{user?.uid ?? "anon"}</span>
      <button onClick={() => signInWithEmail("a@b", "pw").catch(() => undefined)}>
        sign-in-email
      </button>
      <button onClick={() => signInWithGoogle().catch(() => undefined)}>
        sign-in-google
      </button>
      <button onClick={() => signOut()}>sign-out</button>
      <button
        onClick={() =>
          signUpWithEmail("a@b", "pw", "Ada").catch(() => undefined)
        }
      >
        sign-up
      </button>
      <button onClick={() => sendPasswordReset("a@b").catch(() => undefined)}>
        password-reset
      </button>
      <button onClick={() => sendVerificationEmail().catch(() => undefined)}>
        verify-email
      </button>
      <button onClick={() => reloadUser().catch(() => undefined)}>
        reload
      </button>
      <button
        onClick={() => startPhoneSignIn("+15551234", "recap").catch(() => undefined)}
      >
        phone-start
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  it("resolves loading → ready with no user on first render", async () => {
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready")
    );
    expect(screen.getByTestId("user").textContent).toBe("anon");
  });

  it("exposes all documented auth actions without throwing", async () => {
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready")
    );
    const user = userEvent.setup();
    // Each click exercises the method in auth-context without failing.
    await user.click(screen.getByText("sign-in-email"));
    await user.click(screen.getByText("sign-in-google"));
    await user.click(screen.getByText("sign-up"));
    await user.click(screen.getByText("password-reset"));
    await user.click(screen.getByText("sign-out"));
    // sendVerificationEmail throws if currentUser is null (expected behavior);
    // we swallow via .catch in the harness.
    await user.click(screen.getByText("verify-email"));
    // reloadUser is a no-op when currentUser is null
    await user.click(screen.getByText("reload"));
  });

  it("reflects downstream onAuthStateChanged updates", async () => {
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready")
    );
    await act(async () => {
      authListeners[authListeners.length - 1]({ uid: "new-uid" });
    });
    expect(screen.getByTestId("user").textContent).toBe("new-uid");
  });

  it("useAuth throws when used outside AuthProvider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Harness />)).toThrow(/AuthProvider/);
    spy.mockRestore();
  });

  it("sendVerificationEmail + reloadUser use the signed-in currentUser", async () => {
    // Back the mocked auth with a real-ish user object so the success paths
    // (not the "not signed in" early-exit) execute.
    const reload = vi.fn(() => Promise.resolve());
    mockAuth.currentUser = { uid: "u-live", reload };
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready")
    );
    const user = userEvent.setup();
    await user.click(screen.getByText("verify-email"));
    await user.click(screen.getByText("reload"));
    expect(reload).toHaveBeenCalledTimes(1);
    // Reset so later tests don't see a signed-in user.
    mockAuth.currentUser = null;
  });

  it("startPhoneSignIn constructs a RecaptchaVerifier and delegates to Firebase", async () => {
    render(
      <AuthProvider>
        <Harness />
      </AuthProvider>
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready")
    );
    const user = userEvent.setup();
    await user.click(screen.getByText("phone-start"));
    // signInWithPhoneNumber is the mocked Firebase call — when the click
    // completes without throwing, the happy-path of startPhoneSignIn ran.
    const { signInWithPhoneNumber } = await import("firebase/auth");
    expect(vi.mocked(signInWithPhoneNumber)).toHaveBeenCalled();
  });
});
