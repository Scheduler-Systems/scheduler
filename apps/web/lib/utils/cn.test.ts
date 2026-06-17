import { describe, it, expect, vi } from "vitest";
import { cn } from "./cn";

describe("cn", () => {
  it("merges class strings", () => {
    const result = cn("px-4", "py-2");
    expect(result).toBe("px-4 py-2");
  });

  it("filters out falsy values", () => {
    const result = cn("foo", false && "bar", undefined, null, "baz");
    expect(result).toBe("foo baz");
  });

  it("merges tailwind classes with twMerge", () => {
    const result = cn("px-2 py-1", "px-4");
    expect(result).toBe("py-1 px-4");
  });

  it("handles conditional object syntax", () => {
    const result = cn("base", { active: true, disabled: false });
    expect(result).toBe("base active");
  });

  it("handles nested arrays", () => {
    const result = cn(["px-4", ["py-2", "text-sm"]], "font-bold");
    expect(result).toBe("px-4 py-2 text-sm font-bold");
  });

  it("handles empty input", () => {
    const result = cn();
    expect(result).toBe("");
  });

  it("handles only falsy values", () => {
    const result = cn(false, null, undefined, "");
    expect(result).toBe("");
  });

  it("merges conflicting tailwind utilities correctly", () => {
    const result = cn("text-red-500", "text-blue-500");
    expect(result).toBe("text-blue-500");
  });
});
