import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import { getAuth, connectAuthEmulator, type Auth } from "firebase/auth";
import {
  getFirestore,
  connectFirestoreEmulator,
  type Firestore,
} from "firebase/firestore";

// SCRUBBED: all values come from NEXT_PUBLIC_FIREBASE_* env vars. Set these to
// your own Firebase web app config (see .env.local.example). The placeholders
// below are non-functional and exist only so the module is well-typed.
const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "your-project.firebaseapp.com",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "your-firebase-project-id",
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET ?? "your-project.firebasestorage.app",
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "000000000000",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "1:000000000000:web:0000000000000000000000",
};

// Lazy init — Firebase must only run in the browser (not during SSR/prerender)
let _app: FirebaseApp | undefined;
let _auth: Auth | undefined;
let _db: Firestore | undefined;

// Local-dev only: when NEXT_PUBLIC_USE_FIREBASE_EMULATORS=true and running in
// the browser, route Auth/Firestore to the local Firebase emulators (see
// firebase.json) so the app can be exercised end-to-end on dev without touching
// production data or hitting auth/unauthorized-domain on localhost. Never active
// in production (gated on an explicit opt-in env flag).
function shouldUseEmulators(): boolean {
  return (
    typeof window !== "undefined" &&
    process.env.NEXT_PUBLIC_USE_FIREBASE_EMULATORS === "true"
  );
}

export function getFirebaseApp(): FirebaseApp {
  if (!_app) _app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
  return _app;
}

export function getFirebaseAuth(): Auth {
  if (!_auth) {
    _auth = getAuth(getFirebaseApp());
    if (shouldUseEmulators()) {
      connectAuthEmulator(_auth, "http://127.0.0.1:9099", {
        disableWarnings: true,
      });
    }
  }
  return _auth;
}

export function getFirebaseDb(): Firestore {
  if (!_db) {
    _db = getFirestore(getFirebaseApp());
    if (shouldUseEmulators()) {
      connectFirestoreEmulator(_db, "127.0.0.1", 8088);
    }
  }
  return _db;
}
