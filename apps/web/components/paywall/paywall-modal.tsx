"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n-context";
import {
  SEAT_BANDS,
  DEFAULT_SEAT_BAND,
  type SeatBand,
  type SeatBandId,
} from "@/lib/billing/seat-bands";

/**
 * PaywallModal — SEAT-BAND (per-user) pricing modal.
 *
 * Scheduler is priced PER USER (per seat). The real RevenueCat product is a set
 * of pre-existing per-user COUNT BANDS (up to 10 / 20 / 30 / 50 / 100 users),
 * NOT flat tiers. This modal mirrors the live Flutter
 * `users_number_selection_widget`: the buyer picks a seat band and on Continue
 * the matching band is handed to `onSelectBand` — which routes to the band's
 * hosted RevenueCat checkout URL (see `lib/billing/seat-bands.ts` +
 * `startSeatBandCheckout`).
 *
 * PRICE-AGNOSTIC BY DESIGN: this modal asserts NO dollar amount. The RevenueCat
 * hosted checkout page is the single source of truth for price — it renders the
 * real, server-driven per-user charge (Essential / Pro tiers, monthly & annual
 * plans). A previous version advertised "from $2.99/user/mo"; that figure was
 * false (real RC checkout charges well under it and prices can change), so the
 * price assertion was removed rather than swapped for new hardcoded numbers that
 * would only drift again. Copy points buyers to "see your price at checkout".
 *
 * Counts above the largest band (100) are NOT self-serve: they open a
 * contact-sales path (`onContactSales`), matching the Flutter Enterprise chip
 * (which creates a Brevo sales lead, not a purchase).
 *
 * Presentational + selection only: it does not perform the purchase itself and
 * does not enforce gates.
 *
 * Decisions intentionally left open as TODO(decision) — the structure works
 * regardless of how they resolve:
 *   - D-SPLIT: what Professional adds over Essential. Today both are the SAME
 *     per-user product sold by seat band; if/when they diverge, add an
 *     Essential/Pro axis on top of the band selector. Either way price stays at
 *     checkout — never hardcoded here.
 *   - D-FREE: the free-tier caps (currently shown as 3 users / 1 station /
 *     5 builds, carried over from the prior paywall — UNVERIFIED here).
 *   - D-TRIAL: whether a free trial is offered. We claim NO trial (none is wired
 *     today); if a trial is enabled in RevenueCat, add trial copy then.
 */

export type PaywallTrigger = "build" | "station" | "user";

export interface PaywallModalProps {
  /** Whether the modal is currently visible. */
  open: boolean;
  /** Called when the user dismisses (close button, backdrop click, or Escape). */
  onClose: () => void;
  /** What triggered the paywall — controls the context banner copy. */
  trigger: PaywallTrigger;
  /**
   * Called with the selected seat band when the user confirms a purchase. The
   * caller is responsible for routing to the band's hosted checkout (see
   * `startSeatBandCheckout`). Optional so trigger surfaces that only need to
   * *show* the paywall can omit it.
   */
  onSelectBand?: (band: SeatBand) => void;
  /**
   * Called when the user has more seats than the largest band (Enterprise /
   * contact sales). Optional — if omitted, the contact-sales row is hidden.
   */
  onContactSales?: () => void;
}

export function PaywallModal({
  open,
  onClose,
  trigger,
  onSelectBand,
  onContactSales,
}: PaywallModalProps) {
  const { t } = useI18n();
  const titleId = useId();
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);

  // Selected seat band — defaults to the smallest band, mirroring the Flutter
  // default chip ("Up to 10 Users").
  const [selectedSeats, setSelectedSeats] = useState<SeatBandId>(
    DEFAULT_SEAT_BAND.seats,
  );

  // Reset the selection to the default whenever the modal (re)opens so a stale
  // prior choice never carries across triggers.
  useEffect(() => {
    if (open) setSelectedSeats(DEFAULT_SEAT_BAND.seats);
  }, [open]);

  // Escape key handler — only active while the modal is open.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  // Move focus to the close button when opening so keyboard users start
  // at a sensible, well-labelled control.
  useEffect(() => {
    if (open) closeBtnRef.current?.focus();
  }, [open]);

  if (!open) return null;

  const triggerKey =
    trigger === "build"
      ? "paywall.triggerBuild"
      : trigger === "station"
        ? "paywall.triggerStation"
        : "paywall.triggerUser";

  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    // Only close on clicks that start on the backdrop itself — clicks on
    // the card should never bubble up and dismiss.
    if (e.target === e.currentTarget) onClose();
  }

  const selectedBand =
    SEAT_BANDS.find((b) => b.seats === selectedSeats) ?? DEFAULT_SEAT_BAND;

  function handleContinue() {
    onSelectBand?.(selectedBand);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm px-4 py-6"
      onClick={handleBackdropClick}
      data-testid="paywall-backdrop"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-2xl"
      >
        <button
          ref={closeBtnRef}
          type="button"
          onClick={onClose}
          aria-label={t("paywall.closeAria")}
          className="absolute top-3 right-3 flex items-center justify-center w-8 h-8 rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
        >
          <svg
            className="w-5 h-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        <div className="px-6 pt-8 pb-2 sm:px-10">
          <h2
            id={titleId}
            className="text-center text-2xl sm:text-3xl font-semibold tracking-tight text-gray-900"
          >
            {t("paywall.title")}
          </h2>

          {/* Price-agnostic plan clarifier. NO dollar amount is shown here — the
              hosted RevenueCat checkout is the single source of truth for price. */}
          <p
            className="mt-2 text-center text-sm text-gray-500"
            data-testid="paywall-plan-note"
          >
            {t("paywall.planNote")}
          </p>

          <div
            role="status"
            className="mt-4 rounded-lg border border-purple-200 bg-purple-50 px-4 py-3 text-sm text-purple-800"
            data-testid="paywall-trigger-banner"
          >
            {t(triggerKey)}
          </div>
        </div>

        {/* Seat-band selector — mirrors the Flutter choice chips. */}
        <div className="px-6 pb-2 pt-4 sm:px-10">
          <p className="text-sm font-medium text-gray-700">
            {t("paywall.selectSeatsLabel")}
          </p>
          <div
            role="radiogroup"
            aria-label={t("paywall.selectSeatsLabel")}
            className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3"
            data-testid="paywall-band-group"
          >
            {SEAT_BANDS.map((band) => {
              const selected = band.seats === selectedSeats;
              return (
                <button
                  key={band.seats}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setSelectedSeats(band.seats)}
                  data-testid={`paywall-band-${band.seats}`}
                  data-selected={selected ? "true" : "false"}
                  className={
                    selected
                      ? "rounded-lg border-2 border-purple-600 bg-purple-50 px-3 py-2 text-sm font-semibold text-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
                      : "rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:border-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-500"
                  }
                >
                  {t("paywall.bandLabel", { count: band.seats })}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={handleContinue}
            data-testid="paywall-continue"
            className="mt-5 w-full rounded-md bg-purple-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500"
          >
            {t("paywall.continue")}
          </button>

          {/* Free tier reminder (no purchase button). D-FREE: caps unverified. */}
          <p
            className="mt-3 text-center text-xs text-gray-400"
            data-testid="paywall-free-note"
          >
            {t("paywall.freeNote")}
          </p>

          {/* Enterprise / contact-sales — NOT a self-serve purchase. Mirrors the
              Flutter Enterprise chip (Brevo sales lead). Hidden if no handler. */}
          {onContactSales && (
            <button
              type="button"
              onClick={onContactSales}
              data-testid="paywall-contact-sales"
              className="mt-4 w-full rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-purple-500"
            >
              {t("paywall.enterpriseContact")}
            </button>
          )}
        </div>

        <div className="px-6 pb-8 pt-2 sm:px-10" />
      </div>
    </div>
  );
}
