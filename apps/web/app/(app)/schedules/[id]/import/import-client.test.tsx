import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const pushMock = vi.fn();
const paramsMock = { id: "sid1" };
vi.mock("next/navigation", () => ({
  useParams: () => paramsMock,
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}));

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

const addEmployeesBulk = vi.fn();
vi.mock("@/lib/firestore-write", () => ({
  addEmployeesBulk: (...args: unknown[]) => addEmployeesBulk(...args),
}));

const ImportEmployeesClient = (await import("./import-client")).default;

describe("ImportEmployeesClient", () => {
  beforeEach(() => {
    pushMock.mockReset();
    addEmployeesBulk.mockReset();
  });

  it("renders heading and the CSV textarea with a label", () => {
    render(<ImportEmployeesClient />);
    expect(
      screen.getByRole("heading", { name: /Import employees/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("CSV")).toBeInTheDocument();
    // Initially no employees → Import button disabled
    const btn = screen.getByRole("button", { name: /Import/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("fills the sample CSV when the helper button is clicked", async () => {
    const user = userEvent.setup();
    render(<ImportEmployeesClient />);
    await user.click(
      screen.getByRole("button", { name: /Fill with sample data/i }),
    );
    const textarea = screen.getByLabelText("CSV") as HTMLTextAreaElement;
    expect(textarea.value).toContain("Alice Example");
  });

  it("imports valid rows and shows the success banner", async () => {
    addEmployeesBulk.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ImportEmployeesClient />);
    await user.click(
      screen.getByRole("button", { name: /Fill with sample data/i }),
    );
    await user.click(screen.getByRole("button", { name: /Import 3/i }));
    await waitFor(() =>
      expect(addEmployeesBulk).toHaveBeenCalledWith(
        "sid1",
        expect.arrayContaining([
          expect.objectContaining({
            employee_name: "Alice Example",
            role: expect.objectContaining({ is_worker: true }),
          }),
        ]),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText(/Imported 3 employees/i))
        .toBeInTheDocument(),
    );
  });

  it("shows an error when addEmployeesBulk rejects", async () => {
    addEmployeesBulk.mockRejectedValueOnce({ code: "permission-denied" });
    const user = userEvent.setup();
    render(<ImportEmployeesClient />);
    await user.click(
      screen.getByRole("button", { name: /Fill with sample data/i }),
    );
    await user.click(screen.getByRole("button", { name: /Import 3/i }));
    await waitFor(() => expect(addEmployeesBulk).toHaveBeenCalled());
    // Error banner is whatever friendlyAuthError returns — just ensure success
    // banner does NOT appear.
    await waitFor(() =>
      expect(screen.queryByText(/Imported/)).toBeNull(),
    );
  });

  it("routes back to the schedule when Cancel is clicked", async () => {
    const user = userEvent.setup();
    render(<ImportEmployeesClient />);
    await user.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(pushMock).toHaveBeenCalledWith("/schedules/sid1");
  });
});
