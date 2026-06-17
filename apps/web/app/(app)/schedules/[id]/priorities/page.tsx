import PrioritiesClient from "./priorities-client";

export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function PrioritiesPage() {
  return <PrioritiesClient />;
}
