/*
  The mark is the product thesis at 20px: a short unstable signal above a
  settled, measured result.
*/
export function Mark() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect className="mark-signal" x="0" y="4" width="9" height="3.4" rx="0.6" fill="var(--signal)" />
      <rect x="0" y="12.6" width="20" height="3.4" rx="0.6" fill="var(--proof)" />
    </svg>
  );
}

export function Wordmark({ href = "/", label = "Flowstate" }: { href?: string; label?: string }) {
  return (
    <a className="wordmark" href={href}>
      <Mark />
      {label}
    </a>
  );
}
