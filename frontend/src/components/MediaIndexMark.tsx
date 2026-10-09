/** A clapperboard and search lens, drawn as one compact, scalable mark. */
export function MediaIndexMark({ className = "" }: { className?: string }) {
  return <svg className={className} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 12h21v3M4 12v12a2 2 0 0 0 2 2h7" />
    <path d="m3 7 20-5 1.2 4.8-20 5Z" />
    <path d="m8 5.8 3.4 4.2m4-6 3.4 4.2" />
    <circle cx="21" cy="22" r="6" />
    <path d="m25.4 26.4 4.6 4.1" />
  </svg>;
}
