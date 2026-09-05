import type { ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { classNames } from "../../lib/classNames";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success" | "inverse";
type Size = "sm" | "md" | "icon";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const variants: Record<Variant, string> = {
  primary:
    "bg-primary-700 text-white border-primary-700 hover:bg-primary-800 hover:border-primary-800 shadow-sm",
  secondary: "bg-surface text-ink-700 border-ink-200 hover:border-primary-300 hover:bg-primary-50 hover:text-primary-900 shadow-sm",
  ghost: "bg-transparent text-ink-600 border-transparent hover:bg-ink-100 hover:text-ink-900",
  danger: "bg-danger-600 text-white border-danger-600 hover:bg-danger-700 shadow-sm",
  success: "bg-positive-600 text-white border-positive-600 hover:bg-positive-700 shadow-sm",
  inverse: "bg-white/10 text-white border-white/15 hover:bg-white/20 backdrop-blur",
};

const sizes: Record<Size, string> = {
  sm: "min-h-9 px-3 py-1.5 text-xs",
  md: "min-h-10 px-4 py-2 text-sm",
  icon: "size-10 p-0 text-sm",
};

export function Button({
  className,
  variant = "secondary",
  size = "md",
  loading = false,
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={classNames(
        "inline-flex items-center justify-center gap-2 rounded-control border font-semibold transition duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 disabled:active:translate-y-0 motion-reduce:transition-none [&>svg]:shrink-0",
        sizes[size],
        variants[variant],
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}
