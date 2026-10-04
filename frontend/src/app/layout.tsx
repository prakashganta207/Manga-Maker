import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Story to Manga",
  description: "Turn a short story into a black-and-white manga page.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <header className="border-b-4 border-ink bg-paper">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
            <Link href="/" className="text-2xl font-black tracking-tight">
              STORY<span className="mx-1 inline-block -skew-x-12 bg-ink px-2 text-paper">→</span>MANGA
            </Link>
            <Link href="/" className="text-sm font-semibold underline-offset-4 hover:underline">
              New story
            </Link>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
        <footer className="border-t border-ink/20 py-4 text-center text-xs text-ink/60">
          Original characters only · lettering drawn in code, not by the image model
        </footer>
      </body>
    </html>
  );
}
