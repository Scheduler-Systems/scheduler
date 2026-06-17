"use client";

/**
 * ScheduleBuiltCelebration — confetti + "Your new schedule is ready!" moment,
 * shown once when a roster build is successfully published.
 *
 * Flutter parity:
 *   - The confetti machinery mirrors the Flutter app's app-wide
 *     ConfettiAnimationWidget (lib/components/confetti_animation_widget.dart:7-112,
 *     painted in main.dart:589): a full-screen overlay that does NOT capture
 *     pointer events (Flutter: Positioned.fill + IgnorePointer → here:
 *     fixed inset-0 + pointer-events-none), with a gradient pill
 *     (indigo→violet #6366F1 → #8B5CF6, rounded 25px, white bold, soft shadow)
 *     and an auto-dismiss after the burst plays out.
 *   - The CELEBRATED MOMENT is the Flutter "Congrats! Your new schedule is
 *     ready." beat (walkthroughs/new_schedule_created — the post-build
 *     celebration copy, internationalization.dart "NewScheduleCreated").
 *
 * Trigger semantics live in the schedule detail page
 * (app/(app)/schedules/[id]/schedule-detail-client.tsx): the page fires `show`
 * exactly once per successful publishBuiltSchedule(), from the build-success
 * event itself — never derived from load/render state — so it cannot fire on
 * sign-in, hard reload, re-render, or navigation.
 *
 * Implementation choice: a tiny self-contained <canvas> confetti burst (no
 * Lottie/canvas-confetti dependency — keeps the bundle slim, per the round-3
 * brief "no heavy dep if avoidable"). Honors prefers-reduced-motion: the
 * celebratory pill still shows, the particle burst is skipped.
 */

import { useEffect, useRef } from "react";
import { useI18n } from "@/lib/i18n-context";

/** Total on-screen lifetime of the celebration before it auto-dismisses (ms). */
const CELEBRATION_DURATION_MS = 2600;

/** Confetti palette — the Flutter celebration's indigo/violet family + accents. */
const CONFETTI_COLORS = [
  "#6366F1", // indigo (gradient start)
  "#8B5CF6", // violet (gradient end)
  "#6A0DAD", // Scheduler brand purple
  "#F551C9", // FlutterFlow pink accent
  "#FFC107", // amber
  "#22C55E", // success green
];

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  color: string;
  rotation: number;
  vr: number;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export interface ScheduleBuiltCelebrationProps {
  /** When true, the celebration is on screen. */
  show: boolean;
  /** Called once the celebration has fully played out and should be hidden. */
  onDone: () => void;
}

export function ScheduleBuiltCelebration({
  show,
  onDone,
}: ScheduleBuiltCelebrationProps) {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const onDoneRef = useRef(onDone);
  // Keep the latest onDone without retriggering the auto-dismiss timer when the
  // parent passes a new closure each render. (Assign in an effect, not during
  // render, per react-hooks/refs.)
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  // Auto-dismiss timer (mirrors Flutter's auto-hide after the animation).
  useEffect(() => {
    if (!show) return;
    const timer = setTimeout(() => onDoneRef.current(), CELEBRATION_DURATION_MS);
    return () => clearTimeout(timer);
  }, [show]);

  // Canvas confetti burst. Skipped entirely under prefers-reduced-motion (the
  // celebratory pill still renders below).
  useEffect(() => {
    if (!show) return;
    if (prefersReducedMotion()) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const w = () => window.innerWidth;
    const h = () => window.innerHeight;

    // Seed particles bursting upward/outward from the top-center, like the
    // Flutter stack of confetti animations anchored topCenter.
    const particles: Particle[] = [];
    const count = 140;
    for (let i = 0; i < count; i++) {
      const angle = (-Math.PI / 2) + (Math.random() - 0.5) * Math.PI * 1.1;
      const speed = 4 + Math.random() * 7;
      particles.push({
        x: w() / 2 + (Math.random() - 0.5) * w() * 0.4,
        y: h() * 0.18,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 3,
        size: 5 + Math.random() * 7,
        color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        rotation: Math.random() * Math.PI * 2,
        vr: (Math.random() - 0.5) * 0.3,
      });
    }

    const gravity = 0.18;
    const drag = 0.992;
    const start = performance.now();

    const frame = (now: number) => {
      const elapsed = now - start;
      ctx.clearRect(0, 0, w(), h());
      for (const p of particles) {
        p.vy += gravity;
        p.vx *= drag;
        p.vy *= drag;
        p.x += p.vx;
        p.y += p.vy;
        p.rotation += p.vr;
        // Fade out over the lifetime.
        const alpha = Math.max(0, 1 - elapsed / CELEBRATION_DURATION_MS);
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rotation);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
        ctx.restore();
      }
      if (elapsed < CELEBRATION_DURATION_MS) {
        raf = requestAnimationFrame(frame);
      } else {
        ctx.clearRect(0, 0, w(), h());
      }
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [show]);

  if (!show) return null;

  return (
    <div
      className="pointer-events-none fixed inset-0 z-[100] flex items-start justify-center overflow-hidden"
      role="status"
      aria-live="polite"
      data-testid="schedule-built-celebration"
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0 h-full w-full"
        aria-hidden="true"
      />
      {/* Gradient celebration pill — confetti_animation_widget.dart:71-102. */}
      <div
        className="mt-28 rounded-[25px] px-6 py-4 text-center text-xl font-bold text-white shadow-lg"
        style={{
          background: "linear-gradient(90deg, #6366F1 0%, #8B5CF6 100%)",
          boxShadow: "0 4px 10px rgba(0,0,0,0.20)",
        }}
        data-testid="schedule-built-celebration-banner"
      >
        {t("scheduleBuiltCelebration.title")}
      </div>
    </div>
  );
}
