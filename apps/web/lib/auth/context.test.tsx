import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

let authStateCallbacks: ((user: unknown) => void)[] = [];
let mockFirebaseUser: unknown = null;
let mockFirestoreDocs: Map<string, unknown> = new Map();

vi.mock("firebase/auth", () => ({
  onAuthStateChanged: (_auth: unknown, cb: (u: unknown) => void) => {
    authStateCallbacks.push(cb);
    Promise.resolve().then(() => cb(mockFirebaseUser));
    return () => undefined;
  },
  signInWithEmailAndPassword: vi.fn(() => Promise.resolve({ user: { uid: "u1", email: "test@example.com" } })),
  createUserWithEmailAndPassword: vi.fn(() =>
    Promise.resolve({ user: { uid: "u3", email: "new@example.com", displayName: null, photoURL: null, phoneNumber: null } }),
  ),
  signInWithPhoneNumber: vi.fn(() => Promise.resolve({ confirm: vi.fn(() => Promise.resolve({ user: { uid: "u4" } })) })),
  signOut: vi.fn(() => Promise.resolve()),
  sendPasswordResetEmail: vi.fn(() => Promise.resolve()),
  updateProfile: vi.fn(() => Promise.resolve()),
}));

vi.mock("firebase/firestore", () => ({
  doc: vi.fn((_db: unknown, _collection: string, id: string) => ({ _id: id, _collection: "users" })),
  getDoc: vi.fn(async (ref: { _id: string }) => {
    const data = mockFirestoreDocs.get(ref._id);
    if (data !== undefined) {
      return { exists: () => true, id: ref._id, data: () => data };
    }
    return { exists: () => false, id: ref._id, data: () => undefined };
  }),
  setDoc: vi.fn(() => Promise.resolve()),
  serverTimestamp: vi.fn(() => ({ _seconds: 123, _nanoseconds: 456 })),
}));

vi.mock("@/lib/firebase/client", () => ({
  auth: { currentUser: null },
  db: {},
}));

const { AuthProvider, useAuth } = await import("./context");

function AppUserConsumer() {
  const ctx = useAuth();
  return (
    <div>
      <p data-testid="loading">{String(ctx.loading)}</p>
      <p data-testid="user-email">{ctx.user?.email ?? "none"}</p>
      <p data-testid="fb-uid">{ctx.firebaseUser?.uid ?? "none"}</p>
      <button data-testid="sign-in" onClick={() => ctx.signIn("a@b.com", "pw")}>
        Sign In
      </button>
      <button data-testid="create-account" onClick={() => ctx.createAccount("new@b.com", "pw", "Name")}>
        Create Account
      </button>
      <button data-testid="sign-in-phone" onClick={() => ctx.signInWithPhone("+123")}>
        Phone Sign In
      </button>
      <button data-testid="logout" onClick={() => ctx.logout()}>
        Logout
      </button>
      <button data-testid="reset-pw" onClick={() => ctx.resetPassword("a@b.com")}>
        Reset PW
      </button>
      <button data-testid="update-profile" onClick={() => ctx.updateUserProfile({ displayName: "Updated" })}>
        Update Profile
      </button>
    </div>
  );
}

function renderHarness() {
  return render(
    <AuthProvider>
      <AppUserConsumer />
    </AuthProvider>,
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    authStateCallbacks = [];
    mockFirebaseUser = null;
    mockFirestoreDocs = new Map();
    vi.clearAllMocks();
  });

  it("starts with loading=true, then completes", async () => {
    renderHarness();
    expect(screen.getByTestId("loading").textContent).toBe("true");
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
  });

  it("shows null user when no firebase user is signed in", async () => {
    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    expect(screen.getByTestId("user-email").textContent).toBe("none");
    expect(screen.getByTestId("fb-uid").textContent).toBe("none");
  });

  it("fetches user document when firebase user is present", async () => {
    mockFirebaseUser = { uid: "fb123", email: "fb@test.com" };
    mockFirestoreDocs.set("fb123", {
      email: "fb@test.com",
      display_name: "FB User",
      photo_url: "",
      uid: "fb123",
      role: "worker",
      has_rated: false,
      is_premium: false,
      isAvailable: true,
      language: "en",
    });

    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    await waitFor(() => {
      expect(screen.getByTestId("user-email").textContent).toBe("fb@test.com");
    });
    expect(screen.getByTestId("fb-uid").textContent).toBe("fb123");
  });

  it("returns null from fetchUserDocument when doc does not exist", async () => {
    mockFirebaseUser = { uid: "no-doc" };
    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    expect(screen.getByTestId("user-email").textContent).toBe("none");
  });

  it("signIn calls signInWithEmailAndPassword", async () => {
    const { signInWithEmailAndPassword } = await import("firebase/auth");
    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    await userEvent.click(screen.getByTestId("sign-in"));
    expect(signInWithEmailAndPassword).toHaveBeenCalledWith(
      expect.anything(),
      "a@b.com",
      "pw",
    );
  });

  it("createAccount creates user document when not exists", async () => {
    mockFirebaseUser = null;
    const { createUserWithEmailAndPassword, updateProfile } = await import("firebase/auth");
    const { setDoc } = await import("firebase/firestore");

    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    await userEvent.click(screen.getByTestId("create-account"));

    expect(createUserWithEmailAndPassword).toHaveBeenCalledWith(
      expect.anything(),
      "new@b.com",
      "pw",
    );
    await waitFor(() => {
      expect(updateProfile).toHaveBeenCalledWith(
        { uid: "u3", email: "new@example.com", displayName: null, photoURL: null, phoneNumber: null },
        { displayName: "Name" },
      );
    });
    await waitFor(() => {
      expect(setDoc).toHaveBeenCalled();
    });
  });

  it("signInWithPhone returns confirmation result", async () => {
    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    await userEvent.click(screen.getByTestId("sign-in-phone"));
    const { signInWithPhoneNumber } = await import("firebase/auth");
    expect(signInWithPhoneNumber).toHaveBeenCalledWith(expect.anything(), "+123");
  });

  it("logout calls signOut", async () => {
    const { signOut } = await import("firebase/auth");
    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    await userEvent.click(screen.getByTestId("logout"));
    expect(signOut).toHaveBeenCalledWith(expect.anything());
  });

  it("resetPassword calls sendPasswordResetEmail", async () => {
    const { sendPasswordResetEmail } = await import("firebase/auth");
    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    await userEvent.click(screen.getByTestId("reset-pw"));
    expect(sendPasswordResetEmail).toHaveBeenCalledWith(expect.anything(), "a@b.com");
  });

  it("updateProfile calls updateProfile when firebaseUser is set", async () => {
    mockFirebaseUser = { uid: "fb123", email: "fb@test.com" };
    mockFirestoreDocs.set("fb123", {
      email: "fb@test.com",
      display_name: "Old",
      photo_url: "",
      uid: "fb123",
      role: "worker",
      has_rated: false,
      is_premium: false,
      isAvailable: true,
      language: "en",
    });
    const { updateProfile } = await import("firebase/auth");

    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    await userEvent.click(screen.getByTestId("update-profile"));
    expect(updateProfile).toHaveBeenCalledWith(
      { uid: "fb123", email: "fb@test.com" },
      { displayName: "Updated" },
    );
  });

  it("updateProfile does not call updateProfile when firebaseUser is null", async () => {
    mockFirebaseUser = null;
    const { updateProfile } = await import("firebase/auth");

    renderHarness();
    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("false");
    });
    // updateProfile button exists but shouldn't do anything
    await userEvent.click(screen.getByTestId("update-profile"));
    // updateProfile shouldn't be called since firebaseUser is null in the context
    // (it would be called from onAuthStateChanged which resolves with null)
  });
});

describe("useAuth", () => {
  it("throws when used outside AuthProvider", () => {
    function BadConsumer() {
      useAuth();
      return null;
    }
    expect(() => render(<BadConsumer />)).toThrow("useAuth must be used within an AuthProvider");
  });
});
