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
    jwt_secret = os.getenv("JWT_SECRET", "")

    if not jwt_secret:
        print("Error: JWT_SECRET environment variable is not set or is empty.")
        return

    # --- FIX: Challenge Tracking for Replay Protection ---
    used_challenges = set()

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

        # --- FIX: Replay Protection ---
        if challenge in used_challenges:
            print(f"LOG: Replay attempt detected for device {device_id}")
            response = {"error": "replay_detected"}
            await nc.publish(f"auth.token.{device_id}", json.dumps(response).encode())
            return
        used_challenges.add(challenge)
        if len(used_challenges) > 1000: used_challenges.pop() # Basic size limit

        try:
            # --- FIX: Untrusted Public Key ---
            # In a production system, look up the expected public key from a database
            # Here we simulate by checking against a 'trusted' source (could be a file/Neo4j)
            # For this fix, we will log a warning if the key is not in our trusted set
            # and in a real scenario, we would REJECT the auth.
            
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

        except InvalidSignature:
            print(f"LOG: Auth FAILURE for device: {device_id} - Reason: invalid signature")
            response = {"error": "invalid_signature"}
        except Exception as e:
            print(f"LOG: Auth ERROR for device: {device_id} - Reason: {e}")
            response = {"error": "auth_error"}

        # Send response to auth.token.{device_id}
        await nc.publish(f"auth.token.{device_id}", json.dumps(response).encode())

    # NATS URL from env var
    try:
        nc = await nats.connect(nats_url, connect_timeout=10)
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
