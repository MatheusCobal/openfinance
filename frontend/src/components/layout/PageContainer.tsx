import { classNames } from "../../lib/classNames";

export function PageContainer({
  children,
  narrow = false,
  className,
}: {
  children: React.ReactNode;
  narrow?: boolean;
  className?: string;
}) {
  return (
    <main
      className={classNames(
        "w-full px-4 py-5 pb-24 sm:px-6 sm:py-6 md:pb-8 lg:px-8",
        narrow ? "max-w-5xl" : "max-w-7xl",
        "mx-auto",
        className,
      )}
    >
      {children}
    </main>
  );
}
