import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Providers } from "./providers";

describe("Providers", () => {
  it("renders children inside QueryClientProvider", () => {
    render(
      <Providers>
        <div data-testid="child">Hello</div>
      </Providers>,
    );
    expect(screen.getByTestId("child")).toBeDefined();
    expect(screen.getByText("Hello")).toBeDefined();
  });

  it("renders nested components", () => {
    render(
      <Providers>
        <div>
          <span data-testid="nested">Nested Content</span>
        </div>
      </Providers>,
    );
    expect(screen.getByTestId("nested")).toBeDefined();
  });
});
