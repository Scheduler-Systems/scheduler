"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { parseEmployeesCsv, type CsvRole } from "@/lib/csv-employees";
import { addEmployeesBulk } from "@/lib/firestore-write";
import { friendlyAuthError } from "@/lib/auth-validation";
import type { EmployeeDetails, RoleStruct } from "@/lib/types";

function toRoleStruct(role: CsvRole): RoleStruct {
  return {
    is_creator: role === "creator",
    is_admin: role === "admin" || role === "creator",
    is_worker: true,
  };
}

const SAMPLE = `Alice Example,alice@example.com,555-0001,worker
Bob Example,bob@example.com,,admin
Carol Example,,,worker`;

export default function ImportEmployeesClient() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [text, setText] = useState("");
  const [importing, setImporting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [importedCount, setImportedCount] = useState<number | null>(null);

  const parsed = useMemo(() => parseEmployeesCsv(text), [text]);

  async function handleImport() {
    if (!id || parsed.valid.length === 0) return;
    setImporting(true);
    setErrorMsg("");
    try {
      const rows: Omit<EmployeeDetails, "user_ref">[] = parsed.valid.map(
        (r) => ({
          employee_name: r.employee_name,
          employee_email: r.employee_email,
          employee_phone: r.employee_phone,
          role: toRoleStruct(r.role),
        }),
      );
      await addEmployeesBulk(id, rows);
      setImportedCount(rows.length);
      setText("");
    } catch (err) {
      setErrorMsg(friendlyAuthError(err));
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <Link
        href={`/schedules/${id}`}
        className="text-sm text-purple-600 hover:underline"
      >
        ← Back to schedule
      </Link>

      <header>
        <h1 className="text-2xl font-semibold text-gray-900">
          Import employees
        </h1>
        <p className="text-sm text-gray-500">
          Paste a CSV block: <code>name,email,phone,role</code> per line. Role
          can be <code>worker</code>, <code>admin</code>, or{" "}
          <code>creator</code>. Email + phone are optional.
        </p>
      </header>

      {importedCount !== null && (
        <div className="rounded-md bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-800">
          Imported {importedCount} employee{importedCount === 1 ? "" : "s"}.{" "}
          <Link
            href={`/schedules/${id}`}
            className="font-medium underline"
          >
            Return to schedule →
          </Link>
        </div>
      )}

      {errorMsg && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      <div>
        <label htmlFor="csv" className="block text-sm font-medium mb-1">
          CSV
        </label>
        <textarea
          id="csv"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={10}
          placeholder={SAMPLE}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
        <button
          type="button"
          onClick={() => setText(SAMPLE)}
          className="mt-1 text-xs text-purple-600 hover:underline"
        >
          Fill with sample data
        </button>
      </div>

      {text.trim() && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">
            Preview — {parsed.valid.length} valid
            {parsed.errors.length > 0
              ? `, ${parsed.errors.length} skipped`
              : ""}
          </h2>

          {parsed.errors.length > 0 && (
            <ul className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 space-y-1">
              {parsed.errors.map((e, i) => (
                <li key={i}>
                  Line {e.lineNumber}: {e.reason}{" "}
                  <span className="text-gray-500">({e.line})</span>
                </li>
              ))}
            </ul>
          )}

          {parsed.valid.length > 0 && (
            <div className="rounded-md border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Name
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Email
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Phone
                    </th>
                    <th className="px-3 py-2 text-left font-medium text-gray-600">
                      Role
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {parsed.valid.map((r, i) => (
                    <tr key={i} className="border-t border-gray-100">
                      <td className="px-3 py-1.5">{r.employee_name}</td>
                      <td className="px-3 py-1.5 text-gray-600">
                        {r.employee_email || "—"}
                      </td>
                      <td className="px-3 py-1.5 text-gray-600">
                        {r.employee_phone || "—"}
                      </td>
                      <td className="px-3 py-1.5 capitalize">{r.role}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleImport}
          disabled={importing || parsed.valid.length === 0}
          className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {importing
            ? "Importing…"
            : `Import ${parsed.valid.length || ""} employee${
                parsed.valid.length === 1 ? "" : "s"
              }`.trim()}
        </button>
        <button
          type="button"
          onClick={() => router.push(`/schedules/${id}`)}
          className="rounded-md border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
