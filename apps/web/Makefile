.PHONY: dev test emulators

# Local dev — runs the Next.js server against the local Firebase emulators (the
# ideal dev loop: no production data, no auth/unauthorized-domain on localhost).
# Start the emulators first with `make emulators` (in another terminal).
dev:
	NEXT_PUBLIC_USE_FIREBASE_EMULATORS=true npm run dev

test:
	npm test

# Firebase Auth + Firestore + Functions emulators (Auth :9099, Firestore :8088,
# Functions :5001, UI :4001). Functions source is scheduler-api/functions; its
# RevenueCat callable runs against the RC sandbox using ../scheduler-api/functions/.secret.local.
#
# IMPORTANT: the project MUST match the web app's configured Firebase projectId
# (your-firebase-project-id). The Functions emulator embeds the projectId in the
# callable URL (/{projectId}/{region}/{fn}); a mismatch makes the SDK call a
# path the emulator doesn't serve → CORS/404 → billing falls back to an error.
emulators:
	firebase emulators:start --only auth,firestore,functions --project your-firebase-project-id
