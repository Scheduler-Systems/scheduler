import ArchivedClient from "./archived-client";

export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function ArchivedPage() {
  return <ArchivedClient />;
}
