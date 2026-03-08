import json
import os
import hashlib
import time
import boto3
import jwt

sqs = boto3.client("sqs", region_name="eu-west-1")

JWT_SECRET    = os.environ["JWT_SECRET"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]

cors_headers = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
}

def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": cors_headers, "body": ""}

    # Vérifier le JWT
    auth_header = event.get("headers", {}).get("authorization", "")
    token = auth_header.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id  = payload["sub"]
        username = payload["username"]
    except Exception:
        return {
            "statusCode": 401,
            "headers": cors_headers,
            "body": json.dumps({"error": "Unauthorized"})
        }

    # Parser le body
    try:
        body = json.loads(event.get("body", "{}"))
        x     = int(body["x"])
        y     = int(body["y"])
        color = body["color"].upper().strip("#")
        if len(color) != 6:
            raise ValueError("Invalid color")
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": cors_headers,
            "body": json.dumps({"error": f"Invalid body: {e}"})
        }

    # Publier sur SQS
    message = {
        "type":    "WEB_PIXEL",
        "command": "draw",
        "user_id": user_id,
        "username": username,
        "options": [
            {"name": "x",     "value": x},
            {"name": "y",     "value": y},
            {"name": "color", "value": color}
        ],
        "interaction_token": "",
        "application_id":    ""
    }

    dedup_id = hashlib.md5(f"{user_id}{x}{y}{time.time()}".encode()).hexdigest()

    sqs.send_message(
        QueueUrl=SQS_QUEUE_URL,
        MessageBody=json.dumps(message),
        MessageGroupId=user_id,
        MessageDeduplicationId=dedup_id
    )

    return {
        "statusCode": 202,
        "headers": cors_headers,
        "body": json.dumps({"status": "queued", "x": x, "y": y, "color": color})
    }