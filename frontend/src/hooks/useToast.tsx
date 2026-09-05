import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
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
        role={toast?.variant === "error" ? "alert" : "status"}
        aria-live={toast?.variant === "error" ? "assertive" : "polite"}
        aria-atomic="true"
        className={classNames(
          "fixed left-4 right-4 top-4 z-[80] flex items-start gap-3 rounded-xl border px-4 py-3.5 text-sm shadow-overlay transition sm:left-auto sm:max-w-sm motion-reduce:transition-none",
          toast ? "translate-y-0 opacity-100" : "pointer-events-none -translate-y-2 opacity-0",
          toast?.variant === "success" && "border-positive-200 bg-positive-50 text-positive-900",
          toast?.variant === "error" && "border-danger-200 bg-danger-50 text-danger-900",
          (!toast || toast.variant === "info") && "border-primary-200 bg-primary-50 text-primary-900",
        )}
      >
        {toast ? (
          <>
            {toast.variant === "success" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              : toast.variant === "error" ? <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              : <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />}
            <p className="min-w-0 flex-1 leading-relaxed">{toast.message}</p>
            <button type="button" onClick={() => setToast(null)} className="-mr-1 -mt-1 flex size-8 shrink-0 items-center justify-center rounded-lg hover:bg-black/5" aria-label="Dispensar mensagem">
              <X className="size-4" aria-hidden="true" />
            </button>
          </>
        ) : null}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
