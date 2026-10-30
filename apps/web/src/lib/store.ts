"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/**
 * Persisted UI preferences only (never server data). Rehydrated after mount so the
 * first client render matches the server render. The theme itself is persisted by
 * next-themes.
 */
interface UiPrefs {
  sidebarCollapsed: boolean;
  lastProjectId: string | null;
  toggleSidebar: () => void;
  setLastProject: (id: string | null) => void;
}

export const useUiPrefs = create<UiPrefs>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      lastProjectId: null,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setLastProject: (id) => set({ lastProjectId: id }),
    }),
    {
      name: "dataquality.ui",
      version: 1,
      skipHydration: true,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, lastProjectId: s.lastProjectId }),
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<UiPrefs>;
        return {
          ...current,
          sidebarCollapsed: typeof p.sidebarCollapsed === "boolean" ? p.sidebarCollapsed : current.sidebarCollapsed,
          lastProjectId: typeof p.lastProjectId === "string" ? p.lastProjectId : null,
        };
      },
    },
  ),
);
