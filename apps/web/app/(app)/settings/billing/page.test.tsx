import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Entitlements } from "@/lib/billing/entitlements";

// -----------------------------------------------------------------------------
// Mocks — pages under test use Next/Link, auth, billing-context, purchase, and
// the PaywallModal. We stub each so the suite never touches Firebase or the
// network.
// -----------------------------------------------------------------------------

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href: string;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

const useBillingMock = vi.fn();
vi.mock("@/lib/billing-context", () => ({
  useBilling: () => useBillingMock(),
}));

const openManagementPortalMock = vi.fn();
const startSeatBandCheckoutMock = vi.fn();
vi.mock("@/lib/billing/purchase", () => ({
  openManagementPortal: (uid: string) => openManagementPortalMock(uid),
  startSeatBandCheckout: (...args: unknown[]) =>
    startSeatBandCheckoutMock(...args),
}));

// The 30-user band the stub fires — must match the real seat-bands catalog so
// the assertion is meaningful (not an invented id).
const BAND_30 = {
  seats: 30 as const,
  webOfferId: "up-to-30-employees" as const,
  mobileOfferId: "offering-id-30-users" as const,
};

// Lightweight stub for PaywallModal so we can assert open/close + drive seat-band
// selection without pulling the real dialog (which has its own tests).
vi.mock("@/components/paywall/paywall-modal", () => ({
  PaywallModal: ({
    open,
    onClose,
    onSelectBand,
  }: {
    open: boolean;
    onClose: () => void;
    onSelectBand?: (band: unknown) => void;
    trigger: string;
  }) =>
    open ? (
      <div data-testid="paywall-modal" role="dialog">
        <button type="button" onClick={onClose}>
          close
        </button>
        <button
          type="button"
          onClick={() => onSelectBand?.(BAND_30)}
          data-testid="paywall-select-band-30"
        >
          select 30-user band
        </button>
      </div>
    ) : null,
}));

const FREE_TIER: Entitlements = {
  isActive: false,
  tier: "free",
  userLimit: 3,
  stationLimit: 1,
  entitlements: [],
  tierDisplayName: "Free",
};

const PRO_TIER: Entitlements = {
  isActive: true,
  tier: "pro",
  userLimit: 30,
  stationLimit: 5,
  entitlements: ["pro_30"],
  tierDisplayName: "Pro",
};

const BillingSettingsPage = (await import("./page")).default;

// -----------------------------------------------------------------------------
// window.location.assign is a non-configurable getter in jsdom; stub it per
// test so we can assert the navigation without jsdom complaining.
// -----------------------------------------------------------------------------
const originalLocation = window.location;

describe("BillingSettingsPage", () => {
  beforeEach(() => {
    useAuthMock.mockReset();
    useBillingMock.mockReset();
    openManagementPortalMock.mockReset();
    startSeatBandCheckoutMock.mockReset();

    // Default: authenticated user on the free tier.
    useAuthMock.mockReturnValue({
      user: { uid: "uid-1", email: "ada@example.com", displayName: "Ada" },
    });
    useBillingMock.mockReturnValue({
      entitlements: FREE_TIER,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });

    // Redefine window.location with a writable .assign stub.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, assign: vi.fn() },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("shows Free as the heading when getEntitlements returns free tier", () => {
    render(<BillingSettingsPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /^Free$/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("billing-plan-card")).toHaveTextContent(/Free/);
    // Free tier advertises 1 station / 3 users / 5 builds per month.
    expect(screen.getByTestId("billing-limits-card")).toHaveTextContent("1");
    expect(screen.getByTestId("billing-limits-card")).toHaveTextContent("3");
    expect(screen.getByTestId("billing-limits-card")).toHaveTextContent("5");
  });

  it("shows Pro as the heading when getEntitlements returns pro tier", () => {
    useBillingMock.mockReturnValue({
      entitlements: PRO_TIER,
      loading: false,
      error: null,
      refetch: vi.fn(),
    });
    render(<BillingSettingsPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: /^Pro$/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("billing-plan-card")).toHaveTextContent(/Pro/);
    // Pro tier: 5 stations, 30 users (derived from fetcher), builds unlimited
    const limitsCard = screen.getByTestId("billing-limits-card");
    expect(limitsCard).toHaveTextContent("5");
    expect(limitsCard).toHaveTextContent("30");
    expect(limitsCard).toHaveTextContent(/Unlimited/);
  });

  it("renders a loading spinner while entitlements resolve", () => {
    useBillingMock.mockReturnValue({
      entitlements: FREE_TIER,
      loading: true,
      error: null,
      refetch: vi.fn(),
    });
    render(<BillingSettingsPage />);
    expect(screen.getByTestId("billing-loading")).toBeInTheDocument();
    // Cards are hidden while loading.
    expect(screen.queryByTestId("billing-plan-card")).toBeNull();
  });

  it("calls openManagementPortal and navigates when the Manage subscription button is clicked", async () => {
    openManagementPortalMock.mockResolvedValueOnce("https://billing.example.com/manage_abc");
    const user = userEvent.setup();
    render(<BillingSettingsPage />);
    await user.click(screen.getByTestId("billing-manage-subscription"));
    await waitFor(() => expect(openManagementPortalMock).toHaveBeenCalledWith("uid-1"));
    await waitFor(() =>
      expect(window.location.assign).toHaveBeenCalledWith(
        "https://billing.example.com/manage_abc",
      ),
    );
  });

  it("surfaces an inline error when openManagementPortal rejects", async () => {
    openManagementPortalMock.mockRejectedValueOnce(
      new Error("NO_SUBSCRIPTIONS: contact support"),
    );
    const user = userEvent.setup();
    render(<BillingSettingsPage />);
    await user.click(screen.getByTestId("billing-manage-subscription"));
    await waitFor(() =>
      expect(screen.getByTestId("billing-portal-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("billing-portal-error")).toHaveTextContent(
      /NO_SUBSCRIPTIONS/,
    );
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("opens the paywall modal when Upgrade plan is clicked", async () => {
    const user = userEvent.setup();
    render(<BillingSettingsPage />);
    expect(screen.queryByTestId("paywall-modal")).toBeNull();
    await user.click(screen.getByTestId("billing-upgrade-plan"));
    expect(screen.getByTestId("paywall-modal")).toBeInTheDocument();
  });

  it("closes the paywall modal when its onClose fires", async () => {
    const user = userEvent.setup();
    render(<BillingSettingsPage />);
    await user.click(screen.getByTestId("billing-upgrade-plan"));
    expect(screen.getByTestId("paywall-modal")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /close/i }));
    expect(screen.queryByTestId("paywall-modal")).toBeNull();
  });

  it("shows the billing error banner when useBilling reports an error", () => {
    useBillingMock.mockReturnValue({
      entitlements: FREE_TIER,
      loading: false,
      error: new Error("cloud function down"),
      refetch: vi.fn(),
    });
    render(<BillingSettingsPage />);
    expect(screen.getByTestId("billing-error-banner")).toBeInTheDocument();
    // Fallback is still the Free tier label — page stays functional.
    expect(
      screen.getByRole("heading", { level: 1, name: /^Free$/i }),
    ).toBeInTheDocument();
  });

  it("disables Manage subscription when there is no signed-in user", () => {
    useAuthMock.mockReturnValue({ user: null });
    render(<BillingSettingsPage />);
    const btn = screen.getByTestId("billing-manage-subscription");
    expect(btn).toBeDisabled();
  });

  it("wires seat-band selection to startSeatBandCheckout (with the band + signed-in Firebase uid, not email)", async () => {
    startSeatBandCheckoutMock.mockResolvedValueOnce({ status: "success" });
    const user = userEvent.setup();
    render(<BillingSettingsPage />);
    await user.click(screen.getByTestId("billing-upgrade-plan"));
    await user.click(screen.getByTestId("paywall-select-band-30"));
    // RevenueCat customer is keyed by uid (matches the read-back), never email.
    // The band object (with the real offering id) is passed through verbatim.
    await waitFor(() =>
      expect(startSeatBandCheckoutMock).toHaveBeenCalledWith(BAND_30, "uid-1"),
    );
  });

  it("surfaces a purchase error from startSeatBandCheckout", async () => {
    startSeatBandCheckoutMock.mockResolvedValueOnce({
      status: "error",
      message: "Couldn't open checkout. Please try again.",
    });
    const user = userEvent.setup();
    render(<BillingSettingsPage />);
    await user.click(screen.getByTestId("billing-upgrade-plan"));
    await user.click(screen.getByTestId("paywall-select-band-30"));
    await waitFor(() =>
      expect(screen.getByTestId("billing-purchase-error")).toHaveTextContent(
        /Couldn't open checkout/i,
      ),
    );
  });
});
