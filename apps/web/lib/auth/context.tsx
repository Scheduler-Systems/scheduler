"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPhoneNumber,
  signOut,
  sendPasswordResetEmail,
  updateProfile,
  type User as FirebaseUser,
  type ConfirmationResult,
} from "firebase/auth";
import { doc, getDoc, setDoc, serverTimestamp } from "firebase/firestore";
import { auth, db } from "@/lib/firebase/client";
import type { User } from "@/types/user";

interface AuthContextType {
  user: User | null;
  firebaseUser: FirebaseUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  createAccount: (email: string, password: string, displayName?: string) => Promise<void>;
  signInWithPhone: (phoneNumber: string) => Promise<ConfirmationResult>;
  confirmPhoneCode: (confirmationResult: ConfirmationResult, code: string) => Promise<void>;
  logout: () => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  updateUserProfile: (data: { displayName?: string; photoURL?: string }) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (fbUser) => {
      setFirebaseUser(fbUser);
      
      if (fbUser) {
        const userDoc = await fetchUserDocument(fbUser.uid);
        setUser(userDoc);
      } else {
        setUser(null);
      }
      
      setLoading(false);
    });

    return unsubscribe;
  }, []);

  async function fetchUserDocument(uid: string): Promise<User | null> {
    try {
      const userRef = doc(db, "users", uid);
      const userSnap = await getDoc(userRef);
      
      if (userSnap.exists()) {
        const data = userSnap.data();
        return {
          id: userSnap.id,
          email: data.email ?? "",
          displayName: data.display_name ?? "",
          photoUrl: data.photo_url ?? "",
          uid: data.uid ?? uid,
          createdTime: data.created_time?.toDate() ?? null,
          phoneNumber: data.phone_number ?? "",
          role: data.role ?? "worker",
          hasRated: data.has_rated ?? false,
          shortDescription: data.shortDescription ?? "",
          lastActiveTime: data.last_active_time?.toDate() ?? null,
          title: data.title ?? "",
          buildCount: data.build_count ?? 0,
          isPremium: data.is_premium ?? false,
          isAvailable: data.isAvailable ?? false,
          version: data.version ?? "",
          language: data.language ?? "en",
          isEnterprise: data.is_enterprise ?? false,
        };
      }
      return null;
    } catch {
      return null;
    }
  }

  async function createUserDocument(fbUser: FirebaseUser, displayName?: string) {
    const userRef = doc(db, "users", fbUser.uid);
    const userSnap = await getDoc(userRef);
    
    if (!userSnap.exists()) {
      await setDoc(userRef, {
        uid: fbUser.uid,
        email: fbUser.email,
        display_name: displayName ?? fbUser.displayName ?? "",
        photo_url: fbUser.photoURL ?? "",
        phone_number: fbUser.phoneNumber ?? "",
        created_time: serverTimestamp(),
        role: "worker",
        has_rated: false,
        is_premium: false,
        isAvailable: true,
        language: "en",
      });
    }
  }

  async function signIn(email: string, password: string) {
    await signInWithEmailAndPassword(auth, email.trim(), password);
  }

  async function createAccount(email: string, password: string, displayName?: string) {
    const credential = await createUserWithEmailAndPassword(auth, email.trim(), password);
    if (displayName && credential.user) {
      await updateProfile(credential.user, { displayName });
    }
    if (credential.user) {
      await createUserDocument(credential.user, displayName);
    }
  }

  async function signInWithPhone(phoneNumber: string): Promise<ConfirmationResult> {
    return await signInWithPhoneNumber(auth, phoneNumber);
  }

  async function confirmPhoneCode(confirmationResult: ConfirmationResult, code: string) {
    const credential = await confirmationResult.confirm(code);
    if (credential.user) {
      await createUserDocument(credential.user);
    }
  }

  async function logout() {
    await signOut(auth);
  }

  async function resetPassword(email: string) {
    await sendPasswordResetEmail(auth, email);
  }

  async function updateUserProfile(data: { displayName?: string; photoURL?: string }) {
    if (firebaseUser) {
      await updateProfile(firebaseUser, data);
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        firebaseUser,
        loading,
        signIn,
        createAccount,
        signInWithPhone,
        confirmPhoneCode,
        logout,
        resetPassword,
        updateUserProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
