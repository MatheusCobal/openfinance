import { useRef } from "react";
import { classNames } from "../../lib/classNames";

interface TabItem<T extends string> {
  key: T;
  label: string;
}

interface TabsProps<T extends string> {
  items: Array<TabItem<T>>;
  value: T;
  onChange: (value: T) => void;
  label?: string;
}

/** Segmented control — quieter than button-tabs, reads as one component. */
export function Tabs<T extends string>({ items, value, onChange, label = "Selecionar visualização" }: TabsProps<T>) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  return (
    <div
      role="tablist"
      aria-label={label}
      className="chip-strip inline-flex max-w-full gap-1 overflow-x-auto rounded-xl border border-ink-200/80 bg-surface-muted p-1"
    >
      {items.map((item, index) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            ref={(element) => { tabRefs.current[index] = element; }}
            onClick={() => onChange(item.key)}
            onKeyDown={(event) => {
              const next = event.key === "ArrowRight" ? (index + 1) % items.length
                : event.key === "ArrowLeft" ? (index - 1 + items.length) % items.length
                : event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : null;
              if (next === null) return;
              event.preventDefault();
              onChange(items[next].key);
              tabRefs.current[next]?.focus();
            }}
            className={classNames(
              "min-h-10 shrink-0 rounded-lg px-4 py-2 text-sm font-semibold transition-colors duration-150",
              active
                ? "bg-surface text-primary-900 shadow-sm ring-1 ring-ink-200/60"
                : "text-ink-500 hover:bg-white/60 hover:text-ink-800",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
