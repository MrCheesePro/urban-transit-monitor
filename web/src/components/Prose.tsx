import type { ReactNode } from 'react'

// A readable column for long text pages (how it works, privacy, terms). It styles the plain
// headings, paragraphs, lists, and links placed inside it, so those pages can be written as simple
// HTML.
export function Prose({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-3xl py-8 text-base leading-relaxed [&_a]:underline [&_a]:underline-offset-4 [&_dd]:mb-4 [&_dd]:text-muted-foreground [&_dt]:font-semibold [&_h2]:mb-3 [&_h2]:mt-10 [&_h2]:font-display [&_h2]:text-2xl [&_h2]:font-bold [&_h2]:uppercase [&_h2]:tracking-wide [&_li]:mb-2 [&_ol]:mb-4 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:mb-4 [&_ul]:mb-4 [&_ul]:list-disc [&_ul]:pl-6">
      {children}
    </div>
  )
}
