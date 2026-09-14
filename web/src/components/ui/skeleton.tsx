import { cn } from "@/lib/utils"

// A gray placeholder block (shadcn/ui) that gently pulses while content loads. The pulse is calmed by
// the reduced-motion rule in index.css for people who ask for less motion.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-accent", className)}
      {...props}
    />
  )
}

export { Skeleton }
