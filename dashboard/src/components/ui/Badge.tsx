import * as React from "react";
import { cn } from "../../lib/utils";

const Badge = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { variant?: "default" | "secondary" | "destructive" | "outline" | "success" }>(
  ({ className, variant = "default", ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-zinc-300 focus:ring-offset-2",
          {
            "border-transparent bg-zinc-50 text-zinc-900 hover:bg-zinc-50/80": variant === "default",
            "border-transparent bg-zinc-800 text-zinc-50 hover:bg-zinc-800/80": variant === "secondary",
            "border-transparent bg-red-900 text-zinc-50 hover:bg-red-900/80": variant === "destructive",
            "border-transparent bg-emerald-500/15 text-emerald-500 hover:bg-emerald-500/25": variant === "success",
            "text-zinc-50 border-zinc-800": variant === "outline",
          },
          className
        )}
        {...props}
      />
    );
  }
);
Badge.displayName = "Badge";

export { Badge };
