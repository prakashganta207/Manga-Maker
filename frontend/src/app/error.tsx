"use client"; // Error boundaries must be Client Components

import Link from "next/link";
import { useEffect } from "react";

export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="panel mx-auto max-w-xl space-y-4 p-6">
      <h1 className="text-2xl font-black">Something went wrong on this page</h1>
      <p className="text-sm text-ink/70">
        {error.message || "An unexpected error happened."} Your manga is safe: every step is saved on the server.
      </p>
      <div className="flex gap-3">
        <button type="button" className="btn btn-primary" onClick={() => retry()}>
          Try again
        </button>
        <Link href="/" className="btn">
          Home
        </Link>
      </div>
    </div>
  );
}
