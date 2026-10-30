"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * A tab kept in the address (?tab=...), so a tab can be linked, bookmarked and reloaded.
 * The default tab keeps the address clean; an unknown value falls back to the default.
 */
export function useTabParam<T extends string>(fallback: T, allowed: readonly T[]): [T, (next: string) => void] {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const raw = params.get("tab");
  const tab = (allowed as readonly string[]).includes(raw ?? "") ? (raw as T) : fallback;
  const setTab = (next: string) => router.replace(next === fallback ? pathname : `${pathname}?tab=${next}`, { scroll: false });
  return [tab, setTab];
}
