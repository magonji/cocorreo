import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Concatenates Tailwind classes, letting the last ones win (with smart dedup). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
