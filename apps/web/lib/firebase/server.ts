import { initializeApp, getApps, cert, getApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getFirestore } from "firebase-admin/firestore";

let _adminApp: ReturnType<typeof initializeApp> | null = null;
let _adminAuth: ReturnType<typeof getAuth> | null = null;
let _adminDb: ReturnType<typeof getFirestore> | null = null;

function getAdminApp() {
  if (_adminApp) {
    return _adminApp;
  }
  
  if (getApps().length > 0) {
    _adminApp = getApp();
    return _adminApp;
  }
  
  const privateKey = process.env.FIREBASE_PRIVATE_KEY?.replace(/\\n/g, "\n");
  
  _adminApp = initializeApp({
    credential: cert({
      projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
      clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
      privateKey,
    }),
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  });
  
  return _adminApp;
}

export function getAdminAuth() {
  if (!_adminAuth) {
    _adminAuth = getAuth(getAdminApp());
  }
  return _adminAuth;
}

export function getAdminDb() {
  if (!_adminDb) {
    _adminDb = getFirestore(getAdminApp());
  }
  return _adminDb;
}

export async function verifySessionCookie(sessionCookie: string) {
  try {
    const decoded = await getAdminAuth().verifySessionCookie(sessionCookie, true);
    return { uid: decoded.uid, email: decoded.email, valid: true };
  } catch {
    return { uid: null, email: null, valid: false };
  }
}

export async function createSessionCookie(idToken: string, expiresIn: number = 604800000) {
  return getAdminAuth().createSessionCookie(idToken, { expiresIn });
}

export async function revokeSession(uid: string) {
  await getAdminAuth().revokeRefreshTokens(uid);
}
