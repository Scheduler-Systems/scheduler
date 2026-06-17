import { describe, it, expect } from "vitest";
import { parseEmployeesCsv } from "./csv-employees";

describe("parseEmployeesCsv", () => {
  it("parses a basic name,email,phone,role block", () => {
    const text = `Alice,alice@example.com,555-0001,worker
Bob,bob@example.com,555-0002,admin`;
    const out = parseEmployeesCsv(text);
    expect(out.valid).toHaveLength(2);
    expect(out.valid[0]).toEqual({
      employee_name: "Alice",
      employee_email: "alice@example.com",
      employee_phone: "555-0001",
      role: "worker",
    });
    expect(out.valid[1].role).toBe("admin");
    expect(out.errors).toHaveLength(0);
  });

  it("ignores blank lines and trims whitespace", () => {
    const text = `  Alice ,  alice@example.com ,  ,  worker  \n\n\nBob,,,`;
    const out = parseEmployeesCsv(text);
    expect(out.valid[0].employee_name).toBe("Alice");
    expect(out.valid[0].employee_email).toBe("alice@example.com");
    expect(out.valid[0].employee_phone).toBe("");
    expect(out.valid[1].employee_name).toBe("Bob");
  });

  it("skips header rows (first cell equals 'name' or 'Employee Name')", () => {
    const text = `Name,Email,Phone,Role
Alice,alice@example.com,,worker`;
    const out = parseEmployeesCsv(text);
    expect(out.valid).toHaveLength(1);
    expect(out.valid[0].employee_name).toBe("Alice");
  });

  it("defaults missing role to 'worker'", () => {
    const text = `Alice,alice@example.com`;
    const out = parseEmployeesCsv(text);
    expect(out.valid[0].role).toBe("worker");
  });

  it("normalises role aliases (case-insensitive)", () => {
    const text = `A,,,ADMIN\nB,,,Admins\nC,,,worker\nD,,,creator\nE,,,random`;
    const out = parseEmployeesCsv(text);
    const roles = out.valid.map((r) => r.role);
    expect(roles).toEqual(["admin", "admin", "worker", "creator", "worker"]);
  });

  it("flags rows with an invalid email format", () => {
    const text = `Alice,not-an-email,,worker`;
    const out = parseEmployeesCsv(text);
    expect(out.valid).toHaveLength(0);
    expect(out.errors).toHaveLength(1);
    expect(out.errors[0]).toMatchObject({
      lineNumber: 1,
      reason: expect.stringMatching(/email/i),
    });
  });

  it("flags rows missing a name", () => {
    const text = `,alice@example.com,,worker`;
    const out = parseEmployeesCsv(text);
    expect(out.errors).toHaveLength(1);
    expect(out.errors[0].reason).toMatch(/name/i);
  });

  it("returns empty arrays for empty input", () => {
    const out = parseEmployeesCsv("   \n\n   ");
    expect(out.valid).toEqual([]);
    expect(out.errors).toEqual([]);
  });

  it("is tolerant of trailing commas", () => {
    const text = `Alice,alice@example.com,,worker,extra,,`;
    const out = parseEmployeesCsv(text);
    expect(out.valid).toHaveLength(1);
    expect(out.valid[0].employee_name).toBe("Alice");
  });
});
