"use client";

import { createContext, useContext, useEffect, useState } from "react";
import {
  User,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  signOut as firebaseSignOut,
  createUserWithEmailAndPassword,
  updateProfile,
  sendPasswordResetEmail,
  sendEmailVerification,
  RecaptchaVerifier,
  signInWithPhoneNumber,
  type ConfirmationResult,
} from "firebase/auth";
import { getFirebaseAuth } from "./firebase";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  signUpWithEmail: (
    email: string,
    password: string,
    displayName: string,
  ) => Promise<void>;
  sendPasswordReset: (email: string) => Promise<void>;
  sendVerificationEmail: () => Promise<void>;
  reloadUser: () => Promise<void>;
  startPhoneSignIn: (
    phoneNumber: string,
    recaptchaContainerId: string,
  ) => Promise<ConfirmationResult>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const googleProvider = new GoogleAuthProvider();

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    return onAuthStateChanged(getFirebaseAuth(), (u) => {
      setUser(u);
      setLoading(false);
    });
  }, []);

  async function signInWithEmail(email: string, password: string) {
    await signInWithEmailAndPassword(getFirebaseAuth(), email, password);
  }

  async function signInWithGoogle() {
    await signInWithPopup(getFirebaseAuth(), googleProvider);
  }

  async function signOut() {
    await firebaseSignOut(getFirebaseAuth());
  }

  async function signUpWithEmail(
    email: string,
    password: string,
    displayName: string,
  ) {
    const cred = await createUserWithEmailAndPassword(
      getFirebaseAuth(),
      email,
      password,
    );
    const trimmed = displayName.trim();
    if (trimmed) {
      await updateProfile(cred.user, { displayName: trimmed });
    }
  }

  async function sendPasswordReset(email: string) {
    await sendPasswordResetEmail(getFirebaseAuth(), email);
  }

  async function sendVerificationEmail() {
    const u = getFirebaseAuth().currentUser;
    if (!u) throw new Error("Not signed in.");
    await sendEmailVerification(u);
  }

  async function reloadUser() {
    const u = getFirebaseAuth().currentUser;
    if (!u) return;
    await u.reload();
    setUser({ ...u });
  }

  async function startPhoneSignIn(
    phoneNumber: string,
    recaptchaContainerId: string,
  ): Promise<ConfirmationResult> {
    const auth = getFirebaseAuth();
    const verifier = new RecaptchaVerifier(auth, recaptchaContainerId, {
      size: "invisible",
    });
    try {
      return await signInWithPhoneNumber(auth, phoneNumber, verifier);
    } catch (err) {
      verifier.clear();
      throw err;
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        signInWithEmail,
        signInWithGoogle,
        signOut,
        signUpWithEmail,
        sendPasswordReset,
        sendVerificationEmail,
        reloadUser,
        startPhoneSignIn,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
