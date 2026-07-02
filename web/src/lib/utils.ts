import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Concatena clases Tailwind dejando ganar a las últimas (con dedup inteligente). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
