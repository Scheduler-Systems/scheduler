// Simple CSV parser for bulk employee import. No dependency on a CSV library —
// pasted-in spreadsheet data doesn't need full RFC 4180. Columns (in order):
//   name, email, phone, role
// Missing columns are treated as empty. Header rows (first cell looks like
// "Name" or "Employee Name") are auto-skipped.

import { isValidEmail } from "./auth-validation";

export type CsvRole = "worker" | "admin" | "creator";

export interface CsvEmployeeRow {
  employee_name: string;
  employee_email: string;
  employee_phone: string;
  role: CsvRole;
}

export interface CsvEmployeeError {
  lineNumber: number;
  line: string;
  reason: string;
}

export interface ParseResult {
  valid: CsvEmployeeRow[];
  errors: CsvEmployeeError[];
}

const HEADER_ALIASES = new Set([
  "name",
  "employee name",
  "full name",
  "first name",
]);

function normaliseRole(input: string): CsvRole {
  const r = input.trim().toLowerCase();
  if (r.startsWith("admin")) return "admin";
  if (r.startsWith("creator") || r.startsWith("owner")) return "creator";
  return "worker";
}

function isHeader(firstCell: string): boolean {
  return HEADER_ALIASES.has(firstCell.trim().toLowerCase());
}

export function parseEmployeesCsv(text: string): ParseResult {
  const valid: CsvEmployeeRow[] = [];
  const errors: CsvEmployeeError[] = [];

  const lines = text.split(/\r?\n/);
  let dataLine = 0;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    const cells = line.split(",").map((c) => c.trim());
    if (dataLine === 0 && isHeader(cells[0] ?? "")) {
      dataLine = 1;
      continue;
    }
    dataLine += 1;

    const [name = "", email = "", phone = "", role = ""] = cells;

    if (!name) {
      errors.push({
        lineNumber: dataLine,
        line,
        reason: "Missing employee name.",
      });
      continue;
    }

    if (email && !isValidEmail(email)) {
      errors.push({
        lineNumber: dataLine,
        line,
        reason: `Invalid email: ${email}`,
      });
      continue;
    }

    valid.push({
      employee_name: name,
      employee_email: email,
      employee_phone: phone,
      role: normaliseRole(role),
    });
  }

  return { valid, errors };
}
