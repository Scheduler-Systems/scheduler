import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AppState {
  currentScheduleId: string | null;
  sidebarOpen: boolean;
  onboardingStep: number;
  currentDisplayName: string;
  setCurrentSchedule: (id: string | null) => void;
  toggleSidebar: () => void;
  setOnboardingStep: (step: number) => void;
  setCurrentDisplayName: (name: string) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      currentScheduleId: null,
      sidebarOpen: true,
      onboardingStep: 0,
      currentDisplayName: "",
      setCurrentSchedule: (id) => set({ currentScheduleId: id }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setOnboardingStep: (step) => set({ onboardingStep: step }),
      setCurrentDisplayName: (name) => set({ currentDisplayName: name }),
    }),
    {
      name: "scheduler-app-state",
      partialize: (state) => ({
        currentScheduleId: state.currentScheduleId,
        currentDisplayName: state.currentDisplayName,
      }),
    }
  )
);
