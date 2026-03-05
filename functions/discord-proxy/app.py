import json
import os
import boto3
import hashlib
import nacl.signing
import nacl.exceptions
from nacl.encoding import HexEncoder

sqs = boto3.client("sqs", region_name="eu-west-1")
secretsmanager = boto3.client("secretsmanager", region_name="eu-west-1")

_public_key_cache = None

def get_public_key():
    global _public_key_cache
    if _public_key_cache is None:
        response = secretsmanager.get_secret_value(SecretId="discord/public-key")
        _public_key_cache = response["SecretString"]
    return _public_key_cache

def verify_discord_signature(public_key_hex, signature, timestamp, body):
    try:
        verify_key = nacl.signing.VerifyKey(public_key_hex, encoder=HexEncoder)
        verify_key.verify(f"{timestamp}{body}".encode(), bytes.fromhex(signature))
        return True
    except nacl.exceptions.BadSignatureError:
        return False

def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    signature = headers.get("x-signature-ed25519", "")
    timestamp  = headers.get("x-signature-timestamp", "")
    body       = event.get("body", "")

    if not signature or not timestamp:
        return {"statusCode": 401, "body": json.dumps({"error": "Missing signature headers"})}

    try:
        public_key = get_public_key()
        if not verify_discord_signature(public_key, signature, timestamp, body):
            return {"statusCode": 401, "body": json.dumps({"error": "Invalid signature"})}
    except Exception as e:
        print(f"Signature verification error: {e}")
        return {"statusCode": 401, "body": json.dumps({"error": "Signature verification failed"})}

    data = json.loads(body)
    interaction_type = data.get("type")

    if interaction_type == 1:
        return {"statusCode": 200, "body": json.dumps({"type": 1})}

    if interaction_type == 2:
        member       = data.get("member", {})
        user         = member.get("user", {}) if member else data.get("user", {})
        command_name = data.get("data", {}).get("name", "")
        user_id      = data.get("member", {}).get("user", {}).get("id", "")
        guild_id     = data.get("guild_id", "")
        token        = data.get("token", "")
        app_id       = data.get("application_id", "")
        username     = user.get("username", "unknown")

        message = {
            "type": "DISCORD_COMMAND",
            "command": command_name,
            "user_id": user_id,
            "username": username,
            "guild_id": guild_id,
            "interaction_token": token,
            "application_id": app_id,
            "options": data.get("data", {}).get("options", []),
            "raw": data
        }

        queue_url = os.environ["SQS_QUEUE_URL"]
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message),
            MessageGroupId=user_id or "default",
            MessageDeduplicationId=hashlib.md5(token.encode()).hexdigest()
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"type": 5})
        }

    return {"statusCode": 400, "body": json.dumps({"error": "Unhandled interaction type"})}