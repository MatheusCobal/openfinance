import type { HTMLAttributes } from "react";
import { classNames } from "../../lib/classNames";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** `raised` lifts the card slightly; `flat` removes the shadow for nested cards. */
  elevation?: "flat" | "default" | "raised";
}

const elevations = {
  flat: "shadow-none",
  default: "shadow-card",
  raised: "shadow-lift",
};

export function Card({ className, elevation = "default", ...props }: CardProps) {
  return (
    <div
      className={classNames(
        "rounded-card border border-ink-200/70 bg-surface",
        elevations[elevation],
        className,
      )}
      {...props}
    />
  );
}
