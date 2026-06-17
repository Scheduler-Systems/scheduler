import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ShiftGrid } from "./shift-grid";

const DAYS = ["Mon", "Tue", "Wed"];
const SHIFTS = ["morning", "afternoon", "night"] as const;

describe("ShiftGrid", () => {
  it("renders a header cell per day and a row per shift", () => {
    render(<ShiftGrid days={DAYS} shifts={[...SHIFTS]} />);

    DAYS.forEach((d) => expect(screen.getByText(d)).toBeInTheDocument());
    SHIFTS.forEach((s) =>
      expect(screen.getByText(new RegExp(s, "i"))).toBeInTheDocument(),
    );
  });

  it("renders days × shifts data cells", () => {
    const { container } = render(
      <ShiftGrid days={DAYS} shifts={[...SHIFTS]} />,
    );
    const cells = container.querySelectorAll('[data-testid^="cell-"]');
    expect(cells.length).toBe(DAYS.length * SHIFTS.length);
  });

  it("fires onCellClick with { day, shift } when a cell is clicked", async () => {
    const onCellClick = vi.fn();
    const user = userEvent.setup();
    render(
      <ShiftGrid
        days={DAYS}
        shifts={[...SHIFTS]}
        onCellClick={onCellClick}
      />,
    );

    await user.click(screen.getByTestId("cell-Tue-afternoon"));

    expect(onCellClick).toHaveBeenCalledTimes(1);
    expect(onCellClick).toHaveBeenCalledWith({
      day: "Tue",
      shift: "afternoon",
    });
  });

  it("renders assignments in the matching cell", () => {
    render(
      <ShiftGrid
        days={DAYS}
        shifts={[...SHIFTS]}
        assignments={{ "Mon|morning": ["Alice", "Bob"] }}
      />,
    );
    const cell = screen.getByTestId("cell-Mon-morning");
    expect(cell).toHaveTextContent("Alice");
    expect(cell).toHaveTextContent("Bob");
  });

  it("does not fire onCellClick when readOnly is true", async () => {
    const onCellClick = vi.fn();
    const user = userEvent.setup();
    render(
      <ShiftGrid
        days={DAYS}
        shifts={[...SHIFTS]}
        onCellClick={onCellClick}
        readOnly
      />,
    );

    await user.click(screen.getByTestId("cell-Mon-morning"));
    expect(onCellClick).not.toHaveBeenCalled();
  });

  it("renders nothing gracefully when days or shifts is empty", () => {
    const { container, rerender } = render(
      <ShiftGrid days={[]} shifts={[...SHIFTS]} />,
    );
    expect(container.querySelectorAll('[data-testid^="cell-"]').length).toBe(0);

    rerender(<ShiftGrid days={DAYS} shifts={[]} />);
    expect(container.querySelectorAll('[data-testid^="cell-"]').length).toBe(0);
  });
});
