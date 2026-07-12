import * as React from "react";
import { cn } from "../../lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-300 disabled:pointer-events-none disabled:opacity-50",
          {
            "bg-zinc-50 text-zinc-900 shadow hover:bg-zinc-200/90": variant === "default",
            "bg-red-900 text-zinc-50 shadow-sm hover:bg-red-900/90": variant === "destructive",
            "border border-zinc-800 bg-transparent shadow-sm hover:bg-zinc-800 hover:text-zinc-50": variant === "outline",
            "bg-zinc-800 text-zinc-50 shadow-sm hover:bg-zinc-800/80": variant === "secondary",
            "hover:bg-zinc-800 hover:text-zinc-50": variant === "ghost",
            "text-zinc-50 underline-offset-4 hover:underline": variant === "link",
            "h-9 px-4 py-2": size === "default",
            "h-8 rounded-md px-3 text-xs": size === "sm",
            "h-10 rounded-md px-8": size === "lg",
            "h-9 w-9": size === "icon",
          },
          className
        )}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
