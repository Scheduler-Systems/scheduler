# GitHub Actions Secrets Configuration

Required secrets for the iOS release workflow to deploy to TestFlight/App Store.

## App Store Connect API

| Secret | Description | How to Generate |
|--------|-------------|-----------------|
| `APP_STORE_CONNECT_API_KEY_BASE64` | App Store Connect API key (.p8) encoded as base64 | [App Store Connect](https://appstoreconnect.apple.com/access/integrations/api) → Keys → Generate → base64 encode: `base64 -i AuthKey_XXXX.p8 \| pbcopy` |
| `APP_STORE_CONNECT_API_KEY_ID` | API Key ID (e.g., `ABC12DEF34`) | Shown in App Store Connect → Keys |
| `APP_STORE_CONNECT_ISSUER_ID` | Issuer ID (UUID format) | Shown in App Store Connect → Keys |

## Match Code Signing

| Secret | Description | How to Generate |
|--------|-------------|-----------------|
| `MATCH_PASSWORD` | Encryption password for match certificate storage | Create a strong password and store securely |
| `MATCH_SSH_KEY_BASE64` | SSH key for accessing match repo (if using git storage) | `cat ~/.ssh/id_rsa \| base64 \| pbcopy` |
| `MATCH_GIT_BASIC_AUTHORIZATION` | Base64 encoded git credentials (user:token) | `echo -n "user:personal_access_token" \| base64` |

### Google Cloud Storage (Alternative to Git)

| Secret | Description | How to Generate |
|--------|-------------|-----------------|
| `MATCH_GCS_BUCKET` | GCS bucket name for certificates | `your-ios-certificates-bucket` |
| `MATCH_GCS_PROJECT_ID` | GCP project ID | `your-gcp-project-id` |
| `GITHUB_ACTIONS_SA_CREDENTIALS` | Path to GCP service account JSON | Service account JSON file path |

## Fastlane Authentication

| Secret | Description | How to Generate |
|--------|-------------|-----------------|
| `FASTLANE_USER` | Apple ID email | Your Apple Developer account email |
| `FASTLANE_PASSWORD` | Apple ID password (or app-specific password) | [Apple ID](https://appleid.apple.com) → Security → App-Specific Passwords |

## App Configuration

| Secret | Description | Default |
|--------|-------------|---------|
| `APP_IDENTIFIER` | Bundle identifier | `com.example.scheduler` |
| `APPLE_TEAM_ID` | Apple Developer Team ID | `YOUR_APPLE_TEAM_ID` |
| `APPLE_ID` | Apple ID email | `you@example.com` |

## Setup Commands

```bash
# Encode API key for GitHub secret
base64 -i AuthKey_XXXX.p8 | pbcopy

# Encode SSH key for match repo access
cat ~/.ssh/id_rsa | base64 | pbcopy

# Generate basic auth for git
echo -n "github-user:personal_access_token" | base64
```

## Adding Secrets to GitHub

1. Go to repo → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Add each secret from the tables above
4. Verify by triggering a release workflow
