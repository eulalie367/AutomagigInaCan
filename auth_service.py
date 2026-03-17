import asyncio
import base64
import json
import os
import time
import jwt
import nats
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

async def run_auth_service():
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
    jwt_secret = os.getenv("JWT_SECRET", "required_secret_not_set")

    if jwt_secret == "required_secret_not_set":
        print("Error: JWT_SECRET environment variable is not set.")
        return

    async def message_handler(msg):
        # Handle malformed JSON without crashing
        try:
            payload = json.loads(msg.data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            print("LOG: Received malformed message (invalid JSON or encoding)")
            return

        device_id = payload.get("device_id")
        pub_key_b64 = payload.get("public_key_b64")
        sig_b64 = payload.get("signature_b64")
        challenge = payload.get("challenge")

        # Basic validation of required fields
        if not all([device_id, pub_key_b64, sig_b64, challenge]):
            print(f"LOG: Auth attempt rejected - Missing fields for device {device_id}")
            return

        try:
            # Verify the ATECC608B signature (ECDSA P-256, SHA-256)
            pub_key_bytes = base64.b64decode(pub_key_b64)
            signature_bytes = base64.b64decode(sig_b64)
            challenge_bytes = challenge.encode()

            # Attempt to load public key (handles DER or raw ATECC608B 64-byte format)
            try:
                public_key = serialization.load_der_public_key(pub_key_bytes)
            except Exception:
                if len(pub_key_bytes) == 64:
                    # ATECC608B raw keys are 64 bytes (X, Y). SEC1 requires 0x04 prefix for uncompressed.
                    public_key = ec.EllipticCurvePublicKey.from_encoded_point(
                        ec.SECP256R1(), b"\x04" + pub_key_bytes
                    )
                else:
                    raise ValueError("Invalid public key format or length")

            # Handle ATECC608B raw signature (64 bytes: R, S) vs DER
            if len(signature_bytes) == 64:
                r = int.from_bytes(signature_bytes[:32], "big")
                s = int.from_bytes(signature_bytes[32:], "big")
                der_signature = ec.utils.encode_dss_signature(r, s)
            else:
                der_signature = signature_bytes

            public_key.verify(
                der_signature,
                challenge_bytes,
                ec.ECDSA(hashes.SHA256())
            )

            # If valid, publish a signed JWT to auth.token.{device_id}
            now = int(time.time())
            token = jwt.encode({
                "device_id": device_id,
                "iat": now,
                "exp": now + 3600
            }, jwt_secret, algorithm="HS256")

            print(f"LOG: Auth SUCCESS for device: {device_id}")
            response = {"token": token}

        except (InvalidSignature, Exception) as e:
            # If invalid, publish {"error": "invalid_signature"} to the same subject
            print(f"LOG: Auth FAILURE for device: {device_id} - Reason: {str(e)}")
            response = {"error": "invalid_signature"}

        # Send response to auth.token.{device_id}
        await nc.publish(f"auth.token.{device_id}", json.dumps(response).encode())

    # NATS URL from env var
    try:
        nc = await nats.connect(nats_url)
        print(f"LOG: Connected to NATS at {nats_url}")
    except Exception as e:
        print(f"LOG: Failed to connect to NATS: {e}")
        return

    # Subscribe to NATS subject auth.challenge.response
    await nc.subscribe("auth.challenge.response", cb=message_handler)

    # Process messages until interrupted
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await nc.close()

if __name__ == "__main__":
    try:
        asyncio.run(run_auth_service())
    except KeyboardInterrupt:
        pass
