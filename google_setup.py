"""One-time Google OAuth setup for Billy — run this on your laptop, not the Pi.

Requests exactly two READ-ONLY scopes (Gmail + Calendar). Do not use
strands-google's built-in runner (`python -m strands_google.google_auth`):
its default scopes include full Gmail send/modify, Drive, Photos, and
Contacts, which a fish does not need.

Usage:
    python google_setup.py
        Runs the browser OAuth flow. Needs gmail_credentials.json in the
        current directory (OAuth "Desktop app" client JSON from Google
        Cloud Console). Writes gmail_token.json.

    python google_setup.py --secret-id billy/google-token
        Same, then pushes the token into AWS Secrets Manager under that
        name and deletes the local token file. The Pi fetches it at boot
        (see BILLY_GOOGLE_SECRET_ID in billy_tools.py) so no Google
        credential lives on the SD card.
"""

import json
import os
import sys

from strands_google.google_auth import authenticate_google_oauth

READONLY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

TOKEN_FILE = "gmail_token.json"


def main():
    secret_id = None
    if "--secret-id" in sys.argv:
        secret_id = sys.argv[sys.argv.index("--secret-id") + 1]

    creds = authenticate_google_oauth(
        "gmail_credentials.json", TOKEN_FILE, scopes=READONLY_SCOPES
    )
    if not creds:
        print("Authentication failed - is gmail_credentials.json here?")
        sys.exit(1)

    if not secret_id:
        print(f"Token written to {os.path.abspath(TOKEN_FILE)}")
        print("Copy it to the Pi and set:")
        print(f"  export GOOGLE_OAUTH_CREDENTIALS=/home/morgan/{TOKEN_FILE}")
        return

    import boto3

    with open(TOKEN_FILE) as f:
        token_json = f.read()
    sm = boto3.client("secretsmanager")
    try:
        resp = sm.create_secret(Name=secret_id, SecretString=token_json)
        print(f"Created secret {secret_id}")
    except sm.exceptions.ResourceExistsException:
        resp = sm.put_secret_value(SecretId=secret_id, SecretString=token_json)
        print(f"Updated existing secret {secret_id}")
    arn = resp["ARN"]
    os.remove(TOKEN_FILE)
    print("Local token file deleted. On the Pi, set:")
    print(f"  export BILLY_GOOGLE_SECRET_ID={secret_id}")
    print("\nThen grant the fish read access. If you use the iot-identity")
    print("setup, redeploy the stack with the secret's ARN - the template")
    print("handles the rest:")
    print(f"  aws cloudformation deploy --region us-east-1 \\\n"
          f"    --stack-name billy-bass-identity \\\n"
          f"    --template-file iot-identity/billy-iot.yaml \\\n"
          f"    --parameter-overrides GoogleTokenSecretArn={arn} \\\n"
          f"    --capabilities CAPABILITY_NAMED_IAM")
    print("\nOtherwise, allow secretsmanager:GetSecretValue on this ARN for")
    print(f"whatever IAM identity the Pi uses:\n  {arn}")


if __name__ == "__main__":
    main()
