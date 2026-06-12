import type { ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { classNames } from "../../lib/classNames";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success" | "inverse";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const variants: Record<Variant, string> = {
  primary:
    "bg-primary-600 text-white border-primary-600 hover:bg-primary-700 hover:border-primary-700 shadow-sm",
  secondary: "bg-surface text-ink-700 border-ink-200 hover:bg-ink-50 hover:text-ink-900 shadow-sm",
  ghost: "bg-transparent text-ink-600 border-transparent hover:bg-ink-100 hover:text-ink-900",
  danger: "bg-danger-600 text-white border-danger-600 hover:bg-danger-700 shadow-sm",
  success: "bg-positive-600 text-white border-positive-600 hover:bg-positive-700 shadow-sm",
  inverse: "bg-white/10 text-white border-white/15 hover:bg-white/20 backdrop-blur",
};

const sizes: Record<Size, string> = {
  sm: "min-h-8 px-2.5 py-1 text-xs",
  md: "min-h-9 px-3.5 py-1.5 text-sm",
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
        "inline-flex items-center justify-center gap-2 rounded-control border font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-55",
        sizes[size],
        variants[variant],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}
