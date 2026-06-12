import { classNames } from "../../lib/classNames";

export interface TabItem<T extends string> {
  key: T;
  label: string;
}

interface TabsProps<T extends string> {
  items: Array<TabItem<T>>;
  value: T;
  onChange: (value: T) => void;
}

/** Segmented control — quieter than button-tabs, reads as one component. */
export function Tabs<T extends string>({ items, value, onChange }: TabsProps<T>) {
  return (
    <div
      role="tablist"
      className="chip-strip inline-flex max-w-full gap-1 overflow-x-auto rounded-control border border-ink-200/70 bg-ink-100/70 p-1"
    >
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.key)}
            className={classNames(
              "shrink-0 rounded-[7px] px-3 py-1.5 text-sm font-medium transition-colors duration-150",
              active
                ? "bg-surface text-ink-900 shadow-sm"
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
