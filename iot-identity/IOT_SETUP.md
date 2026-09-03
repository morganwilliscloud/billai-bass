# 🔐 Give Your Fish a Real Identity (AWS IoT Credential Provider)

This is the optional-but-recommended upgrade from "access key in a file" to how real device fleets authenticate: your fish gets an **X.509 certificate** (a device passport), and at runtime it trades that certificate for **temporary AWS credentials** that expire in an hour and can do exactly one thing — talk to Nova 2 Sonic.

Why bother:
- **No long-lived secret on the SD card.** Steal the card, and the credentials on it expire within the hour. The certificate is revocable per-fish with one command.
- **Each fish is individually identifiable and revocable** — relevant if you're building several kits.
- **It's the production pattern.** If you ever build a real device fleet on AWS, you'll do exactly this; the fish is a friendly place to learn it.

What you need before starting: the main BUILD_GUIDE completed through §1.6 (fish talks using the basic access key — get that working first so you're only debugging one thing), the **AWS CLI** configured on your laptop (not the Pi) with admin-ish rights to deploy CloudFormation, and the two files next to this guide: `billy-iot.yaml` and `fish_credentials.py`.

> 🤝 As with everything in this kit: do this with Claude (or your AI assistant of choice). Paste this whole file in and say "walk me through it." If a command errors, paste the error.

---

## Step 1 — Deploy the CloudFormation stack (laptop, ~2 min)

This creates the account-side plumbing: the locked-down role the fish will assume, the **role alias** it's reached through, and the IoT policy that lets a certificate use it.

```bash
aws cloudformation deploy \
  --template-file billy-iot.yaml \
  --stack-name billy-bass-identity \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

Wait for `Successfully created/updated stack`.

## Step 2 — Mint your fish's certificate (laptop, ~3 min)

CloudFormation can't create certificate *private keys* (good — nobody but your fish should ever hold its key). Three commands:

```bash
# 2a. Create the certificate + keypair
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile certificate.pem \
  --public-key-outfile public.key \
  --private-key-outfile private.key \
  --region us-east-1
# Note the "certificateArn" in the output - you need it twice below.

# 2b. Register the fish as a "thing" and bind the certificate to it
aws iot create-thing --thing-name billy-bass --region us-east-1
aws iot attach-thing-principal --thing-name billy-bass \
  --principal YOUR_CERTIFICATE_ARN --region us-east-1

# 2c. Attach the policy (created by the stack) to the certificate
aws iot attach-policy --policy-name billy-bass-assume-role \
  --target YOUR_CERTIFICATE_ARN --region us-east-1
```

Also grab two more files:

```bash
# Amazon's root CA (so the fish can verify it's really talking to AWS)
curl -o AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem

# Your account's personal credentials endpoint
aws iot describe-endpoint --endpoint-type iot:CredentialProvider \
  --region us-east-1 --query endpointAddress --output text > endpoint.txt
```

You now have 4 files that matter: `certificate.pem`, `private.key`, `AmazonRootCA1.pem`, `endpoint.txt`. (You can delete `public.key`.)

## Step 3 — Install the identity on the fish (~2 min)

```bash
# From the directory with the 4 files, on your laptop:
ssh yourusername@billy.local "mkdir -p ~/billy/identity"
scp certificate.pem private.key AmazonRootCA1.pem endpoint.txt \
  yourusername@billy.local:~/billy/identity/

# Lock down the private key, then shred your laptop's copy:
ssh yourusername@billy.local "chmod 600 ~/billy/identity/private.key"
rm private.key
```

That last `rm` matters: after it, the only copy of the fish's private key in the universe lives on the fish. That's the point.

## Step 4 — Nothing to edit

`billy.py` already looks for the identity you just installed. On startup it checks for `~/billy/identity/endpoint.txt`; if it's there, Billy authenticates with the certificate, and if it isn't, he falls back to the ordinary AWS credential chain (the access key). So the same `billy.py` works both ways — installing the four files in Step 3 is all it takes to flip him over.

(Under the hood it imports `fish_credentials.py` from this `iot-identity/` folder in the repo, so there's nothing to copy. Credentials auto-refresh hourly, so always-on fish keep talking.)

## Step 5 — Verify, then revoke the old key

1. Run Billy and have a conversation — he should work exactly as before.
2. Prove the old key is out of the loop: `mv ~/.aws/credentials ~/.aws/credentials.bak` on the Pi, run Billy again. Still talks? The certificate is doing the work.
3. Now make it official — on your laptop, deactivate and delete the `billy-bass` IAM user's access key in the IAM console. The fish no longer has (or needs) any long-lived secret.

## If a fish is lost/stolen/goes rogue

```bash
aws iot update-certificate --certificate-id THE_CERT_ID \
  --new-status REVOKED --region us-east-1
```

That fish stops getting credentials within the hour. Other fish are unaffected.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `403` from the credentials endpoint | Policy not attached to the cert (step 2c), or cert not ACTIVE |
| `ResourceNotFoundException` on role alias | Stack deployed to a different region than the endpoint — everything here is us-east-1 |
| `AccessDeniedException` from Bedrock | Model access for Nova 2 Sonic not granted in Bedrock console |
| `ssl.SSLError` / handshake failure | Wrong file paths in `~/billy/identity/`, or `private.key` doesn't match `certificate.pem` |
| Worked, then died after ~1 hour | Credential refresh failing — run once in the foreground and read the error (cert revoked? clock skew? `endpoint.txt` edited?) |
