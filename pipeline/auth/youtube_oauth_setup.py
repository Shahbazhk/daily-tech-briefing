"""
One-time, LOCAL-ONLY script: run this once on your own machine (never in CI)
to authorize this project against your YouTube channel and print a refresh
token. Requires a Google Cloud OAuth 2.0 Desktop-app client id/secret (create
one at https://console.cloud.google.com/apis/credentials after enabling the
YouTube Data API v3 for your project).

Usage:
  export YOUTUBE_CLIENT_ID=...        # PowerShell: $env:YOUTUBE_CLIENT_ID = "..."
  export YOUTUBE_CLIENT_SECRET=...
  python pipeline/auth/youtube_oauth_setup.py

Opens a browser for you to sign in and grant access, then prints the refresh
token to store as the YOUTUBE_REFRESH_TOKEN GitHub Actions secret.
"""

import os

from google_auth_oauthlib.flow import InstalledAppFlow

# Broad "youtube" scope (not the narrower "youtube.upload") because this project also
# calls playlistItems.insert, which requires the broader scope.
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def main() -> None:
    client_id = os.environ["YOUTUBE_CLIENT_ID"]
    client_secret = os.environ["YOUTUBE_CLIENT_SECRET"]

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    credentials = flow.run_local_server(port=0)

    print("\nSuccess. Store this as the YOUTUBE_REFRESH_TOKEN GitHub Actions secret:\n")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
