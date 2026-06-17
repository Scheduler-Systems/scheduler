# =============================================================================
# Constants - Shared constants for Fastlane configuration
# =============================================================================

APP_NAME = 'Scheduler'
PROJECT_ROOT = File.expand_path('../..', __dir__)
ANDROID_PACKAGE_NAME = ENV['ANDROID_PACKAGE_NAME'] || 'com.example.scheduler'
FIREBASE_PROJECT = ENV['FIREBASE_PROJECT'] || 'your-firebase-project-id'

ENVIRONMENTS = {
  dev: {
    android_package_name: ANDROID_PACKAGE_NAME,
    firebase_project: FIREBASE_PROJECT,
    distribution: 'firebase'
  },
  production: {
    android_package_name: ANDROID_PACKAGE_NAME,
    firebase_project: FIREBASE_PROJECT
  }
}

PRODUCTION_TRACKS = {
  internal: 'internal',
  alpha: 'alpha',
  beta: 'beta',
  production: 'production'
}
