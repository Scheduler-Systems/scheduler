import { Timestamp } from "firebase/firestore";

export interface User {
  id: string;
  email: string;
  displayName: string;
  photoUrl: string;
  uid: string;
  createdTime: Date | null;
  phoneNumber: string;
  role: "manager" | "worker";
  hasRated: boolean;
  shortDescription: string;
  lastActiveTime: Date | null;
  title: string;
  buildCount: number;
  isPremium: boolean;
  isAvailable: boolean;
  version: string;
  language: string;
  isEnterprise: boolean;
}

export interface UserFirestore {
  email?: string;
  display_name?: string;
  photo_url?: string;
  uid?: string;
  created_time?: Timestamp;
  phone_number?: string;
  role?: string;
  has_rated?: boolean;
  shortDescription?: string;
  last_active_time?: Timestamp;
  title?: string;
  build_count?: number;
  is_premium?: boolean;
  isAvailable?: boolean;
  version?: string;
  language?: string;
  is_enterprise?: boolean;
}

export function fromFirestoreUser(id: string, data: UserFirestore): User {
  return {
    id,
    email: data.email ?? "",
    displayName: data.display_name ?? "",
    photoUrl: data.photo_url ?? "",
    uid: data.uid ?? "",
    createdTime: data.created_time?.toDate() ?? null,
    phoneNumber: data.phone_number ?? "",
    role: (data.role as User["role"]) ?? "worker",
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
