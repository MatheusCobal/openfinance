import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { classNames } from "../lib/classNames";

type ToastVariant = "info" | "success" | "error";

interface ToastMessage {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  showToast: (message: string, variant?: ToastVariant) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const showToast = useCallback((message: string, variant: ToastVariant = "info") => {
    const id = Date.now();
    setToast({ id, message, variant });
    window.setTimeout(() => {
      setToast((current) => (current?.id === id ? null : current));
    }, 3800);
  }, []);

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className={classNames(
          "fixed right-4 top-4 z-[80] max-w-sm rounded-control px-4 py-3 text-sm text-white shadow-overlay transition",
          toast ? "translate-y-0 opacity-100" : "pointer-events-none -translate-y-2 opacity-0",
          toast?.variant === "success" && "bg-positive-600",
          toast?.variant === "error" && "bg-danger-600",
          (!toast || toast.variant === "info") && "bg-cockpit-raised",
        )}
      >
        {toast?.message}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
