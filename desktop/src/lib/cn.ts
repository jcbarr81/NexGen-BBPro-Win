/**
 * Tailwind class-name helper.
 *
 * `clsx` handles conditional joins; `tailwind-merge` resolves conflicts in
 * the final string (`"p-2 p-4"` → `"p-4"`). Use liberally in component props
 * that accept `className` so callers can override without fighting specificity.
 */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
