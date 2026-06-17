import { describe, it, expect } from "vitest";
import { isEmployerRole } from "./firestore";

describe("isEmployerRole", () => {
  it("returns true for Flutter-canonical 'employer' string", () => {
    expect(isEmployerRole("employer")).toBe(true);
  });

  it("returns false for Flutter-canonical 'employee' string", () => {
    expect(isEmployerRole("employee")).toBe(false);
  });

  it("returns true for legacy RoleStruct with is_admin", () => {
    expect(isEmployerRole({ is_admin: true, is_worker: true })).toBe(true);
  });

  it("returns true for legacy RoleStruct with is_creator", () => {
    expect(isEmployerRole({ is_creator: true, is_admin: true })).toBe(true);
  });

  it("returns false for legacy RoleStruct with only is_worker", () => {
    expect(isEmployerRole({ is_worker: true })).toBe(false);
  });

  it("returns false for undefined / missing role", () => {
    expect(isEmployerRole(undefined)).toBe(false);
  });

  it("returns false for empty object", () => {
    expect(isEmployerRole({})).toBe(false);
  });
});
