"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/lib/auth";
import { getAuthErrorMessage } from "@/lib/auth/errors";
import { cn } from "@/lib/utils/cn";

const createAccountSchema = z.object({
  displayName: z.string().min(1, "Name is required").max(50, "Name is too long"),
  email: z.string().email("Please enter a valid email"),
  password: z.string().min(6, "Password must be at least 6 characters"),
  confirmPassword: z.string(),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords do not match",
  path: ["confirmPassword"],
});

type CreateAccountFormData = z.infer<typeof createAccountSchema>;

interface CreateAccountFormProps {
  onSuccess?: () => void;
  onSignIn?: () => void;
  className?: string;
}

export function CreateAccountForm({
  onSuccess,
  onSignIn,
  className,
}: CreateAccountFormProps) {
  const { createAccount } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateAccountFormData>({
    resolver: zodResolver(createAccountSchema),
  });

  const onSubmit = async (data: CreateAccountFormData) => {
    setError(null);
    setLoading(true);

    try {
      await createAccount(data.email, data.password, data.displayName);
      onSuccess?.();
    } catch (err) {
      const code = err instanceof Error ? err.message : "unknown";
      setError(getAuthErrorMessage(code));
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className={cn("space-y-4", className)}>
      <div>
        <label htmlFor="displayName" className="block text-sm font-medium text-gray-700">
          Name
        </label>
        <input
          {...register("displayName")}
          type="text"
          autoComplete="name"
          className={cn(
            "mt-1 block w-full rounded-md border px-3 py-2 text-gray-900 shadow-sm",
            "focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500",
            errors.displayName ? "border-red-500" : "border-gray-300"
          )}
          placeholder="John Doe"
        />
        {errors.displayName && (
          <p className="mt-1 text-sm text-red-600">{errors.displayName.message}</p>
        )}
      </div>

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
          autoComplete="new-password"
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

      <div>
        <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700">
          Confirm Password
        </label>
        <input
          {...register("confirmPassword")}
          type="password"
          autoComplete="new-password"
          className={cn(
            "mt-1 block w-full rounded-md border px-3 py-2 text-gray-900 shadow-sm",
            "focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500",
            errors.confirmPassword ? "border-red-500" : "border-gray-300"
          )}
          placeholder="••••••••"
        />
        {errors.confirmPassword && (
          <p className="mt-1 text-sm text-red-600">{errors.confirmPassword.message}</p>
        )}
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-3">
          <p className="text-sm text-red-700">{error}</p>
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
        {loading ? "Creating account..." : "Create Account"}
      </button>

      {onSignIn && (
        <p className="text-center text-sm text-gray-600">
          Already have an account?{" "}
          <button type="button" onClick={onSignIn} className="text-purple-600 hover:underline">
            Sign in
          </button>
        </p>
      )}
    </form>
  );
}
