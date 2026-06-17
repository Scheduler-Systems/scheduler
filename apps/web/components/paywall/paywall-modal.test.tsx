import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@/lib/i18n-context";
import { PaywallModal } from "./paywall-modal";
import { SEAT_BANDS, DEFAULT_SEAT_BAND } from "@/lib/billing/seat-bands";

function wrap(ui: React.ReactNode) {
  return <I18nProvider>{ui}</I18nProvider>;
}

describe("<PaywallModal> (seat-band)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders nothing when `open` is false", () => {
    const onClose = vi.fn();
    render(
      wrap(<PaywallModal open={false} onClose={onClose} trigger="build" />),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders one band button per real RevenueCat seat band", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );

    expect(screen.getByRole("dialog")).toBeTruthy();
    // Exactly the 5 verified bands: 10/20/30/50/100.
    expect(SEAT_BANDS.map((b) => b.seats)).toEqual([10, 20, 30, 50, 100]);
    for (const band of SEAT_BANDS) {
      expect(screen.getByTestId(`paywall-band-${band.seats}`)).toBeTruthy();
    }
    // No band exists outside the verified set.
    expect(screen.queryByTestId("paywall-band-5")).toBeNull();
    expect(screen.queryByTestId("paywall-band-200")).toBeNull();
  });

  it("is PRICE-AGNOSTIC: renders NO hardcoded dollar amount anywhere in the modal", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );
    const dialog = screen.getByRole("dialog");
    const text = dialog.textContent ?? "";
    // No currency symbol and no numeric price of ANY kind may appear. The
    // RevenueCat hosted checkout is the single source of truth for price; the
    // old false "$2.99/user/mo" floor and the dead flat-tier prices are gone.
    expect(text).not.toMatch(/\$/); // no dollar sign
    expect(text).not.toMatch(/\d+\.\d{2}/); // no "X.YZ" price figure
    expect(text).not.toMatch(/2\.99/);
    expect(text).not.toMatch(/4\.99/);
    expect(text).not.toMatch(/9\.99/);
    expect(text).not.toMatch(/19\.99/);
    expect(text).not.toMatch(/29\.99/);
    expect(text).not.toMatch(/99\.99/);
    // The old price element is gone entirely.
    expect(screen.queryByTestId("paywall-price-from")).toBeNull();
    // Price-agnostic copy points buyers to checkout.
    expect(text).toMatch(/checkout/i);
  });

  it("defaults the selection to the smallest band (Up to 10 users)", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );
    const defaultBtn = screen.getByTestId(
      `paywall-band-${DEFAULT_SEAT_BAND.seats}`,
    );
    expect(defaultBtn.getAttribute("data-selected")).toBe("true");
    expect(defaultBtn.getAttribute("aria-checked")).toBe("true");
    // No other band is pre-selected.
    for (const band of SEAT_BANDS) {
      if (band.seats === DEFAULT_SEAT_BAND.seats) continue;
      expect(
        screen.getByTestId(`paywall-band-${band.seats}`).getAttribute("data-selected"),
      ).toBe("false");
    }
  });

  it("Continue fires onSelectBand with the DEFAULT band when nothing is changed", async () => {
    const onSelectBand = vi.fn();
    const user = userEvent.setup();
    render(
      wrap(
        <PaywallModal
          open
          onClose={() => undefined}
          trigger="build"
          onSelectBand={onSelectBand}
        />,
      ),
    );

    await user.click(screen.getByTestId("paywall-continue"));
    expect(onSelectBand).toHaveBeenCalledTimes(1);
    expect(onSelectBand).toHaveBeenCalledWith(DEFAULT_SEAT_BAND);
    // The default band must carry the verified hosted-checkout offer id.
    expect(onSelectBand.mock.calls[0][0].webOfferId).toBe("up-to-10-employees");
  });

  it("selecting the 50-user band routes Continue to offering-id up-to-50-employees", async () => {
    const onSelectBand = vi.fn();
    const user = userEvent.setup();
    render(
      wrap(
        <PaywallModal
          open
          onClose={() => undefined}
          trigger="build"
          onSelectBand={onSelectBand}
        />,
      ),
    );

    await user.click(screen.getByTestId("paywall-band-50"));
    expect(
      screen.getByTestId("paywall-band-50").getAttribute("aria-checked"),
    ).toBe("true");

    await user.click(screen.getByTestId("paywall-continue"));
    expect(onSelectBand).toHaveBeenCalledTimes(1);
    const band = onSelectBand.mock.calls[0][0];
    expect(band.seats).toBe(50);
    expect(band.webOfferId).toBe("up-to-50-employees");
    expect(band.mobileOfferId).toBe("offering-id-50-users");
  });

  it("selecting the 100-user band routes to up-to-100-employees", async () => {
    const onSelectBand = vi.fn();
    const user = userEvent.setup();
    render(
      wrap(
        <PaywallModal
          open
          onClose={() => undefined}
          trigger="build"
          onSelectBand={onSelectBand}
        />,
      ),
    );

    await user.click(screen.getByTestId("paywall-band-100"));
    await user.click(screen.getByTestId("paywall-continue"));
    expect(onSelectBand.mock.calls[0][0].webOfferId).toBe("up-to-100-employees");
  });

  it("renders the Enterprise contact-sales affordance ONLY when onContactSales is provided", async () => {
    const onContactSales = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );
    // Absent by default.
    expect(screen.queryByTestId("paywall-contact-sales")).toBeNull();

    rerender(
      wrap(
        <PaywallModal
          open
          onClose={() => undefined}
          trigger="build"
          onContactSales={onContactSales}
        />,
      ),
    );
    const contact = screen.getByTestId("paywall-contact-sales");
    expect(contact).toBeTruthy();
    await user.click(contact);
    expect(onContactSales).toHaveBeenCalledTimes(1);
  });

  it("fires onClose when the backdrop is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(wrap(<PaywallModal open onClose={onClose} trigger="build" />));

    await user.click(screen.getByTestId("paywall-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT fire onClose when the dialog content is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(wrap(<PaywallModal open onClose={onClose} trigger="build" />));

    await user.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("fires onClose when Escape is pressed", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(wrap(<PaywallModal open onClose={onClose} trigger="build" />));

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fires onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(wrap(<PaywallModal open onClose={onClose} trigger="build" />));

    await user.click(screen.getByRole("button", { name: "Close paywall" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT claim a free trial (D-TRIAL: trial is off / unwired)", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).not.toMatch(/trial/i);
  });

  it("shows the build-trigger banner when trigger='build'", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );
    const banner = screen.getByTestId("paywall-trigger-banner");
    expect(banner.textContent).toMatch(/5 free schedule builds/i);
  });

  it("shows the station-trigger banner when trigger='station'", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="station" />),
    );
    const banner = screen.getByTestId("paywall-trigger-banner");
    expect(banner.textContent).toMatch(/1 station/i);
  });

  it("shows the user-trigger banner when trigger='user'", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="user" />),
    );
    const banner = screen.getByTestId("paywall-trigger-banner");
    expect(banner.textContent).toMatch(/users/i);
  });

  it("resets the band selection back to default when reopened", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );
    // Change selection to 100.
    await user.click(screen.getByTestId("paywall-band-100"));
    expect(
      screen.getByTestId("paywall-band-100").getAttribute("aria-checked"),
    ).toBe("true");

    // Close, then reopen.
    rerender(
      wrap(<PaywallModal open={false} onClose={() => undefined} trigger="build" />),
    );
    rerender(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );

    expect(
      screen
        .getByTestId(`paywall-band-${DEFAULT_SEAT_BAND.seats}`)
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(
      screen.getByTestId("paywall-band-100").getAttribute("aria-checked"),
    ).toBe("false");
  });

  it("is an accessible dialog (role + aria-modal + aria-labelledby) with a seat radiogroup", () => {
    render(
      wrap(<PaywallModal open onClose={() => undefined} trigger="build" />),
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const labelledBy = dialog.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    const title = document.getElementById(labelledBy!);
    expect(title).not.toBeNull();
    expect(title!.textContent).toMatch(/Choose your team size/i);

    // The seat selector is an accessible radiogroup with one radio per band.
    const group = screen.getByTestId("paywall-band-group");
    expect(group.getAttribute("role")).toBe("radiogroup");
    expect(within(group).getAllByRole("radio")).toHaveLength(SEAT_BANDS.length);
  });
});
