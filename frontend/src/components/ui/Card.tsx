import type { ReactNode } from "react";

type CardProps = {
  children: ReactNode;
  className?: string;
  as?: "div" | "section";
  "aria-label"?: string;
  "data-testid"?: string;
};

export function Card({
  children,
  className = "",
  as = "div",
  "aria-label": ariaLabel,
  "data-testid": testId,
}: CardProps) {
  const Component = as;
  return (
    <Component className={`surface ${className}`} aria-label={ariaLabel} data-testid={testId}>
      {children}
    </Component>
  );
}
