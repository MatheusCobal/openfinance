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

export function Tabs<T extends string>({ items, value, onChange }: TabsProps<T>) {
  return (
    <div className="chip-strip flex gap-2 overflow-x-auto pb-1">
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onChange(item.key)}
            className={classNames(
              "shrink-0 rounded-md border px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "border-blue-700 bg-blue-700 text-white"
                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-950",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
