"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/lib/auth";
import { getAuthErrorMessage } from "@/lib/auth/errors";
import { cn } from "@/lib/utils/cn";
import type { ConfirmationResult } from "firebase/auth";

const phoneSchema = z.object({
  phoneNumber: z
    .string()
    .min(10, "Please enter a valid phone number")
    .regex(/^\+?[1-9]\d{1,14}$/, "Please enter a valid phone number with country code"),
});

const codeSchema = z.object({
  code: z.string().length(6, "Verification code must be 6 digits"),
});

type PhoneFormData = z.infer<typeof phoneSchema>;
type CodeFormData = z.infer<typeof codeSchema>;

interface PhoneFormProps {
  onSuccess?: () => void;
  className?: string;
}

export function PhoneForm({ onSuccess, className }: PhoneFormProps) {
  const { signInWithPhone, confirmPhoneCode } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirmationResult, setConfirmationResult] = useState<ConfirmationResult | null>(null);
  const [codeSent, setCodeSent] = useState(false);

  const phoneForm = useForm<PhoneFormData>({
    resolver: zodResolver(phoneSchema),
  });

  const codeForm = useForm<CodeFormData>({
    resolver: zodResolver(codeSchema),
  });

  const handleSendCode = async (data: PhoneFormData) => {
    setError(null);
    setLoading(true);

    try {
      const result = await signInWithPhone(data.phoneNumber);
      setConfirmationResult(result);
      setCodeSent(true);
    } catch (err) {
      const code = err instanceof Error ? err.message : "unknown";
      setError(getAuthErrorMessage(code));
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyCode = async (data: CodeFormData) => {
    if (!confirmationResult) return;

    setError(null);
    setLoading(true);

    try {
      await confirmPhoneCode(confirmationResult, data.code);
      onSuccess?.();
    } catch (err) {
      const code = err instanceof Error ? err.message : "unknown";
      setError(getAuthErrorMessage(code));
    } finally {
      setLoading(false);
    }
  };

  if (codeSent) {
    return (
      <form onSubmit={codeForm.handleSubmit(handleVerifyCode)} className={cn("space-y-4", className)}>
        <div className="rounded-md bg-purple-50 p-3">
          <p className="text-sm text-purple-700">
            Verification code sent! Please check your phone.
          </p>
        </div>

        <div>
          <label htmlFor="code" className="block text-sm font-medium text-gray-700">
            Verification Code
          </label>
          <input
            {...codeForm.register("code")}
            type="text"
            inputMode="numeric"
            maxLength={6}
            className={cn(
              "mt-1 block w-full rounded-md border px-3 py-2 text-center text-2xl tracking-widest text-gray-900 shadow-sm",
              "focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500",
              codeForm.formState.errors.code ? "border-red-500" : "border-gray-300"
            )}
            placeholder="000000"
          />
          {codeForm.formState.errors.code && (
            <p className="mt-1 text-sm text-red-600">{codeForm.formState.errors.code.message}</p>
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
          {loading ? "Verifying..." : "Verify Code"}
        </button>

        <button
          type="button"
          onClick={() => {
            setCodeSent(false);
            setConfirmationResult(null);
            codeForm.reset();
          }}
          className="w-full text-sm text-gray-600 hover:underline"
        >
          Use a different number
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={phoneForm.handleSubmit(handleSendCode)} className={cn("space-y-4", className)}>
      <div>
        <label htmlFor="phoneNumber" className="block text-sm font-medium text-gray-700">
          Phone Number
        </label>
        <input
          {...phoneForm.register("phoneNumber")}
          type="tel"
          autoComplete="tel"
          className={cn(
            "mt-1 block w-full rounded-md border px-3 py-2 text-gray-900 shadow-sm",
            "focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500",
            phoneForm.formState.errors.phoneNumber ? "border-red-500" : "border-gray-300"
          )}
          placeholder="+1 (555) 000-0000"
        />
        {phoneForm.formState.errors.phoneNumber && (
          <p className="mt-1 text-sm text-red-600">
            {phoneForm.formState.errors.phoneNumber.message}
          </p>
        )}
        <p className="mt-1 text-xs text-gray-500">
          Include country code (e.g., +1 for US)
        </p>
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
        {loading ? "Sending..." : "Send Verification Code"}
      </button>
    </form>
  );
}
