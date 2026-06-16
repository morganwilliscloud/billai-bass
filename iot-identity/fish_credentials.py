"""Fetch temporary AWS credentials using the fish's device certificate.

This is the AWS IoT credential provider pattern: the fish presents its
X.509 certificate over mutual TLS and receives temporary credentials
(valid ~1 hour) for a role that can only invoke Nova 2 Sonic.

No long-lived AWS secret ever exists on the device.

Files expected in ~/billy/identity/ (created during IOT_SETUP.md):
    certificate.pem  - this fish's certificate
    private.key      - this fish's private key (never leaves the device)
    AmazonRootCA1.pem - Amazon's root CA (to verify we're talking to AWS)
    endpoint.txt     - your account's IoT credentials endpoint hostname
"""

import json
import ssl
import urllib.request
from pathlib import Path

import boto3
import botocore.credentials
import botocore.session

IDENTITY_DIR = Path.home() / "billy" / "identity"
ROLE_ALIAS = "billy-bass-role-alias"
THING_NAME = "billy-bass"


def _fetch_credentials() -> dict:
    """Exchange the device certificate for temporary AWS credentials."""
    endpoint = (IDENTITY_DIR / "endpoint.txt").read_text().strip()
    url = f"https://{endpoint}/role-aliases/{ROLE_ALIAS}/credentials"

    context = ssl.create_default_context(
        cafile=str(IDENTITY_DIR / "AmazonRootCA1.pem")
    )
    context.load_cert_chain(
        certfile=str(IDENTITY_DIR / "certificate.pem"),
        keyfile=str(IDENTITY_DIR / "private.key"),
    )

    request = urllib.request.Request(
        url, headers={"x-amzn-iot-thingname": THING_NAME}
    )
    with urllib.request.urlopen(request, context=context, timeout=10) as response:
        payload = json.loads(response.read())

    creds = payload["credentials"]
    return {
        "access_key": creds["accessKeyId"],
        "secret_key": creds["secretAccessKey"],
        "token": creds["sessionToken"],
        "expiry_time": creds["expiration"],
    }


def fish_boto_session(region: str = "us-east-1") -> boto3.Session:
    """A boto3 Session whose credentials come from the device certificate.

    Credentials auto-refresh before expiry, so long conversations and
    always-on fish keep working across the 1-hour credential lifetime.
    """
    refreshable = botocore.credentials.RefreshableCredentials.create_from_metadata(
        metadata=_fetch_credentials(),
        refresh_using=_fetch_credentials,
        method="custom-iot-certificate",
    )
    session = botocore.session.get_session()
    session._credentials = refreshable
    session.set_config_variable("region", region)
    return boto3.Session(botocore_session=session)
