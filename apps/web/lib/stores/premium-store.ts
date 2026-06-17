import { create } from "zustand";

interface PremiumState {
  isPremium: boolean;
  subscriptionTier: "free" | "pro" | "enterprise" | null;
  subscriptionExpiry: Date | null;
  setPremium: (isPremium: boolean) => void;
  setSubscriptionTier: (tier: PremiumState["subscriptionTier"]) => void;
  setSubscriptionExpiry: (expiry: Date | null) => void;
}

export const usePremiumStore = create<PremiumState>((set) => ({
  isPremium: false,
  subscriptionTier: null,
  subscriptionExpiry: null,
  setPremium: (isPremium) => set({ isPremium }),
  setSubscriptionTier: (tier) => set({ subscriptionTier: tier }),
  setSubscriptionExpiry: (expiry) => set({ subscriptionExpiry: expiry }),
}));
