import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";
import { Button } from "./Button";

interface ModalProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
}

// A classification editor can open above the transaction list. Only the top
// dialog receives keyboard events, and the page stays locked until both close.
const dialogStack: HTMLElement[] = [];
let savedBodyOverflow = "";
let originalPageFocus: HTMLElement | null = null;
const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function syncDialogStack() {
  dialogStack.forEach((dialog, index) => {
    const isCovered = index < dialogStack.length - 1;
    dialog.inert = isCovered;
    if (isCovered) dialog.setAttribute("aria-hidden", "true");
    else dialog.removeAttribute("aria-hidden");
  });
}

export function Modal({ open, title, subtitle, onClose, children }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  const subtitleId = useId();
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (dialogStack.length === 0) {
      savedBodyOverflow = document.body.style.overflow;
      originalPageFocus = previousFocus;
      document.body.style.overflow = "hidden";
    }
    dialogStack.push(dialog);
    syncDialogStack();
    const focusableElements = () => Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
      .filter((element) => element.tabIndex >= 0 && element.getClientRects().length > 0);
    const frame = window.requestAnimationFrame(() => {
      if (dialogStack[dialogStack.length - 1] === dialog) {
        (focusableElements()[0] ?? dialog).focus();
      }
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (dialogStack[dialogStack.length - 1] !== dialog) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusableElements();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || !last) {
        event.preventDefault();
        dialog.focus();
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      const wasTop = dialogStack[dialogStack.length - 1] === dialog;
      const position = dialogStack.indexOf(dialog);
      if (position !== -1) dialogStack.splice(position, 1);
      syncDialogStack();
      if (dialogStack.length === 0) {
        document.body.style.overflow = savedBodyOverflow;
        const returnTo = previousFocus?.isConnected ? previousFocus : originalPageFocus;
        if (returnTo?.isConnected) returnTo.focus({ preventScroll: true });
        originalPageFocus = null;
      } else if (wasTop && previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
      <button
        type="button"
        aria-label="Fechar"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-ink-950/45 backdrop-blur-[4px]"
      />
      <div
        role="dialog"
        ref={dialogRef}
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={subtitle ? subtitleId : undefined}
        className="relative flex max-h-[92dvh] w-full max-w-3xl flex-col rounded-t-[1.5rem] border border-ink-200/70 bg-surface shadow-overlay outline-none sm:max-h-[86dvh] sm:rounded-[1.5rem]"
      >
        <header className="flex items-start justify-between gap-4 rounded-t-[inherit] border-b border-ink-100 bg-surface-muted/60 px-5 py-5 sm:px-6">
          <div className="min-w-0">
            <h2 id={titleId} className="text-lg font-semibold tracking-tight text-ink-900">{title}</h2>
            {subtitle ? <p id={subtitleId} className="mt-1 text-sm leading-relaxed text-ink-500">{subtitle}</p> : null}
          </div>
          <Button type="button" variant="ghost" size="icon" className="shrink-0" aria-label="Fechar janela" onClick={onClose}>
            <X className="size-4" aria-hidden="true" />
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </div>
    </div>
  );
}
