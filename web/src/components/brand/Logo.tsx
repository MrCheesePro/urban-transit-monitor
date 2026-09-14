import { cn } from '@/lib/utils'

// The Linecheck mark: a route line with three stops and a timing tick rising from the middle stop,
// which is filled in the "on time" green. Hidden from screen readers because the wordmark next to
// it already says the name.
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="7" fill="#15181C" />
      <path d="M7 21H25" stroke="#F8FAF9" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M16 21V9" stroke="#F8FAF9" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="8" cy="21" r="2.75" fill="#F8FAF9" />
      <circle cx="16" cy="21" r="3.25" fill="#2E7D5B" stroke="#F8FAF9" strokeWidth="1.5" />
      <circle cx="24" cy="21" r="2.75" fill="#F8FAF9" />
    </svg>
  )
}

// The mark followed by the "Linecheck" wordmark in the display face, as used in the header.
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark className="size-8" />
      <span className="font-display text-2xl font-bold uppercase leading-none tracking-wide">
        Linecheck
      </span>
    </span>
  )
}
