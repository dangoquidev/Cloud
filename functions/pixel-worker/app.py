from email import message
import json
import os
import time
import boto3
import requests
from boto3.dynamodb.conditions import Attr

dynamodb  = boto3.resource("dynamodb", region_name="eu-west-1")
sqs       = boto3.client("sqs", region_name="eu-west-1")
secretsmanager = boto3.client("secretsmanager", region_name="eu-west-1")

canvas_table     = dynamodb.Table("canvas-pixels")
rate_limit_table = dynamodb.Table("rate-limits")
sessions_table   = dynamodb.Table("sessions")

_bot_token_cache = None

RATE_LIMIT = 20  # pixels par minute
SNAPSHOT_QUEUE_URL = os.environ.get("SNAPSHOT_QUEUE_URL")

def get_bot_token():
    global _bot_token_cache
    if _bot_token_cache is None:
        r = secretsmanager.get_secret_value(SecretId="discord/bot-token")
        _bot_token_cache = r["SecretString"]
    return _bot_token_cache

def send_discord_response(app_id, token, content):
    """Envoie une réponse async à Discord via followup webhook."""
    url = f"https://discord.com/api/v10/webhooks/{app_id}/{token}"
    headers = {"Content-Type": "application/json"}
    payload = {"content": content}
    requests.post(url, headers=headers, json=payload)

def get_session_status():
    try:
        r = sessions_table.get_item(Key={"PK": "SESSION#CURRENT", "SK": "METADATA"})
        return r.get("Item", {}).get("status", "active")
    except:
        return "active"

def check_rate_limit(user_id):
    """Retourne True si l'utilisateur a dépassé la limite."""
    minute_window = str(int(time.time()) // 60)
    pk = f"RATELIMIT#{user_id}"
    sk = f"WINDOW#{minute_window}"
    ttl = int(time.time()) + 120  # expire dans 2 minutes

    try:
        response = rate_limit_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="ADD #count :inc SET #ttl = if_not_exists(#ttl, :ttl)",
            ExpressionAttributeNames={"#count": "count", "#ttl": "TTL"},
            ExpressionAttributeValues={":inc": 1, ":ttl": ttl},
            ReturnValues="UPDATED_NEW"
        )
        count = int(response["Attributes"]["count"])
        return count > RATE_LIMIT
    except Exception as e:
        print(f"Rate limit check error: {e}")
        return False

def draw_pixel(user_id, username, x, y, color):
    chunk_x = int(x) // 100
    chunk_y = int(y) // 100
    pk = f"CHUNK#{chunk_x}#{chunk_y}"
    sk = f"PIXEL#{x}#{y}"
    timestamp = str(int(time.time()))

    canvas_table.put_item(Item={
        "PK": pk,
        "SK": sk,
        "x": int(x),
        "y": int(y),
        "color": color,
        "author_id": user_id,
        "author_name": username,      # ← ajouté
        "updated_at": timestamp
    })

def handle_draw(message):
    user_id = message["user_id"]
    username = message.get("username", user_id)  # ← ajouté
    app_id  = message["application_id"]
    token   = message["interaction_token"]
    options = {o["name"]: o["value"] for o in message.get("options", [])}

    x     = options.get("x")
    y     = options.get("y")
    color = options.get("color", "").upper().strip("#")

    # Valider la couleur
    if len(color) != 6:
        send_discord_response(app_id, token, "❌ Couleur invalide. Utilise un format hex 6 caractères (ex: FF0000)")
        return

    # Vérifier la session
    status = get_session_status()
    if status == "paused":
        send_discord_response(app_id, token, "⏸️ La session est en pause. Attends qu'un admin la relance.")
        return

    # Vérifier le rate limit
    if check_rate_limit(user_id):
        send_discord_response(app_id, token, f"⏱️ Rate limit atteint ! Max {RATE_LIMIT} pixels/minute.")
        return

    # Dessiner le pixel
    draw_pixel(user_id, username, x, y, f"#{color}")
    send_discord_response(app_id, token, f"✅ Pixel ({x}, {y}) dessiné en #{color} !")

def handle_session(message):
    options = {o["name"]: o["value"] for o in message.get("options", [])}
    action  = options.get("action", "")
    app_id  = message["application_id"]
    token   = message["interaction_token"]
    user_id = message["user_id"]

    sessions_table.put_item(Item={
        "PK": "SESSION#CURRENT",
        "SK": "METADATA",
        "status": action if action in ["active", "paused"] else "active",
        "started_by": user_id,
        "updated_at": str(int(time.time()))
    })

    msgs = {"start": "▶️ Session démarrée !", "pause": "⏸️ Session en pause.", "reset": "🔄 Session réinitialisée."}
    send_discord_response(app_id, token, msgs.get(action, "✅ Action effectuée."))

def lambda_handler(event, context):
    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])
            command = message.get("command", "")
            print(f"Processing command: {command} from user: {message.get('user_id')}")

            if command == "draw":
                handle_draw(message)
            elif command == "session":
                handle_session(message)
            elif command == "canvas":
                import hashlib
                sqs.send_message(
                    QueueUrl=SNAPSHOT_QUEUE_URL,
                    MessageBody=record["body"],
                    MessageGroupId=message.get("user_id", "canvas"),
                    MessageDeduplicationId=hashlib.md5(
                        message.get("interaction_token", "canvas").encode()
                    ).hexdigest()
                )
                print(f"Forwarded canvas command to snapshot queue")
            else:
                print(f"Unknown command: {command}")

        except Exception as e:
            print(f"Error processing record: {e}")
            raise  # Re-raise pour que SQS retry

    return {"statusCode": 200}