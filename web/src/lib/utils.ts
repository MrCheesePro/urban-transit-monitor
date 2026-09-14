import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// Join class names, dropping empty or false ones, and let a later Tailwind class override an
// earlier conflicting one (for example "p-2" then "p-4" keeps only "p-4"). Every UI component
// uses this to combine its default styles with styles passed in by the caller.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
