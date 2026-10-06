import Link from "next/link";

export default function NotFound() {
  return (
    <div className="panel mx-auto max-w-xl space-y-4 p-6">
      <h1 className="text-2xl font-black">Page not found</h1>
      <p className="text-sm text-ink/70">This page doesn&apos;t exist. Looking for a manga? Your series are listed on the Series page.</p>
      <div className="flex gap-3">
        <Link href="/projects" className="btn btn-primary">
          Series
        </Link>
        <Link href="/" className="btn">
          Home
        </Link>
      </div>
    </div>
  );
}
