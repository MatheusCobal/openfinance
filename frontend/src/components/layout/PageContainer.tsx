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
      id="main-content"
      tabIndex={-1}
      className={classNames(
        "w-full min-w-0 px-4 py-6 pb-28 focus-visible:outline-none sm:px-6 md:pb-10 lg:px-8 xl:px-10 xl:py-8",
        narrow ? "max-w-5xl" : "max-w-[1440px]",
        "mx-auto",
        className,
      )}
    >
      {children}
    </main>
  );
}
