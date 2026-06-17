import ImportEmployeesClient from "./import-client";

export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function ImportEmployeesPage() {
  return <ImportEmployeesClient />;
}
