# =============================================================================
# RELEASE SECRETS REQUIRED
# =============================================================================
#
# Configure these secrets in GitHub repository settings before using the release workflow.
#
# =============================================================================

## Google Cloud Authentication (WIF)
GCP_WORKLOAD_IDENTITY_PROVIDER: "projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/providers/PROVIDER_ID"
GCP_SERVICE_ACCOUNT: "service-account@project.iam.gserviceaccount.com"

## Firebase Configuration
FIREBASE_PROJECT: "your-firebase-project-id"
FIREBASE_ANDROID_APP_ID: "1:123456789:android:abcdef"
FIREBASE_ANDROID_API_KEY: "AIza..."

## Google Play Console (for Play Store uploads)
# Service account JSON key file (base64 encoded or file path)
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_PATH: "~/.fastlane/google_play_service_account.json"

## Android Package Name (optional, defaults to com.example.scheduler)
ANDROID_PACKAGE_NAME: "com.yourcompany.app"
