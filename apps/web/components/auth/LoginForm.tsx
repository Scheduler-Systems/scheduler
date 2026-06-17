"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/lib/auth";
import { getAuthErrorMessage } from "@/lib/auth/errors";
import { cn } from "@/lib/utils/cn";

const loginSchema = z.object({
  email: z.string().email("Please enter a valid email"),
  password: z.string().min(6, "Password must be at least 6 characters"),
});

type LoginFormData = z.infer<typeof loginSchema>;

interface LoginFormProps {
  onSuccess?: () => void;
  onForgotPassword?: () => void;
  onSignUp?: () => void;
  className?: string;
}

export function LoginForm({
  onSuccess,
  onForgotPassword,
  onSignUp,
  className,
}: LoginFormProps) {
  const { signIn, resetPassword } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resetEmailSent, setResetEmailSent] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
    getValues,
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginFormData) => {
    setError(null);
    setLoading(true);

    try {
      await signIn(data.email, data.password);
      onSuccess?.();
    } catch (err) {
      const code = err instanceof Error ? err.message : "unknown";
      setError(getAuthErrorMessage(code));
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPassword = async () => {
    const email = getValues("email");
    if (!email) {
      setError("Please enter your email address first");
      return;
    }

    try {
      await resetPassword(email);
      setResetEmailSent(true);
      setError(null);
    } catch (err) {
      const code = err instanceof Error ? err.message : "unknown";
      setError(getAuthErrorMessage(code));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className={cn("space-y-4", className)}>
      <div>
        <label htmlFor="email" className="block text-sm font-medium text-gray-700">
          Email
        </label>
        <input
          {...register("email")}
          type="email"
          autoComplete="email"
          className={cn(
            "mt-1 block w-full rounded-md border px-3 py-2 text-gray-900 shadow-sm",
            "focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500",
            errors.email ? "border-red-500" : "border-gray-300"
          )}
          placeholder="you@example.com"
        />
        {errors.email && (
          <p className="mt-1 text-sm text-red-600">{errors.email.message}</p>
        )}
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium text-gray-700">
          Password
        </label>
        <input
          {...register("password")}
          type="password"
          autoComplete="current-password"
          className={cn(
            "mt-1 block w-full rounded-md border px-3 py-2 text-gray-900 shadow-sm",
            "focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500",
            errors.password ? "border-red-500" : "border-gray-300"
          )}
          placeholder="••••••••"
        />
        {errors.password && (
          <p className="mt-1 text-sm text-red-600">{errors.password.message}</p>
        )}
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {resetEmailSent && (
        <div className="rounded-md bg-green-50 p-3">
          <p className="text-sm text-green-700">Password reset email sent!</p>
        </div>
      )}

      <button
        type="submit"
        disabled={loading}
        className={cn(
          "w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white",
          "hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50"
        )}
      >
        {loading ? "Signing in..." : "Sign In"}
      </button>

      <div className="flex items-center justify-between text-sm">
        <button
          type="button"
          onClick={() => {
            if (onForgotPassword) {
              onForgotPassword();
            } else {
              handleForgotPassword();
            }
          }}
          className="text-purple-600 hover:underline"
        >
          Forgot password?
        </button>
        {onSignUp && (
          <button type="button" onClick={onSignUp} className="text-purple-600 hover:underline">
            Create account
          </button>
        )}
      </div>
    </form>
  );
}
