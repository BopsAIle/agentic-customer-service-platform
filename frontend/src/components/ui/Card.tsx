import type { ReactNode } from "react";

type CardProps = { children: ReactNode; className?: string; as?: "div" | "section" };

export function Card({ children, className = "", as = "div" }: CardProps) {
  const Component = as;
  return <Component className={`surface ${className}`}>{children}</Component>;
}
