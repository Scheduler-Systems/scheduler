# Firebase App Distribution

Firebase App Distribution allows quick distribution of builds to testers.

## Prerequisites

1. Firebase project with App Distribution enabled
2. `firebase_app_id` secret configured in GitHub
3. Firebase CLI installed locally (for manual distribution)

## Distribution

### Manual (via Fastlane)

```bash
cd fastlane
bundle install
bundle exec fastlane distribute_dev
```

### CI/CD

Push a tag or trigger workflow manually via GitHub Actions.
