import { ReactNode } from "react";

/** General page guidance stays in normal flow, separate from action feedback. */
export function PageNote({ children }: { children: ReactNode }) {
  return <p className="next-page-note">{children}</p>;
}
