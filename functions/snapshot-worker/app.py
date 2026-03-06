import json
import os
import io
import time
import boto3
import requests
from PIL import Image, ImageDraw

dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
s3 = boto3.client("s3", region_name="eu-west-1")
secretsmanager = boto3.client("secretsmanager", region_name="eu-west-1")

canvas_table = dynamodb.Table("canvas-pixels")

BUCKET_NAME = os.environ["SNAPSHOT_BUCKET"]
PIXEL_SIZE  = 10  # chaque pixel = 10x10px dans l'image

_bot_token_cache = None

def get_bot_token():
    global _bot_token_cache
    if _bot_token_cache is None:
        r = secretsmanager.get_secret_value(SecretId="discord/bot-token")
        _bot_token_cache = r["SecretString"]
    return _bot_token_cache

def get_all_pixels():
    response = canvas_table.scan()
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = canvas_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return items

def generate_image(pixels):
    if not pixels:
        # Canvas vide → image blanche 100x100
        img = Image.new("RGB", (100 * PIXEL_SIZE, 100 * PIXEL_SIZE), "white")
        return img

    # Calculer les bornes du canvas
    xs = [int(p["x"]) for p in pixels]
    ys = [int(p["y"]) for p in pixels]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Taille de l'image avec padding
    width  = (max_x - min_x + 1) * PIXEL_SIZE
    height = (max_y - min_y + 1) * PIXEL_SIZE

    img  = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    for p in pixels:
        x = (int(p["x"]) - min_x) * PIXEL_SIZE
        y = (int(p["y"]) - min_y) * PIXEL_SIZE
        color = p["color"]  # format "#FF0000"
        draw.rectangle([x, y, x + PIXEL_SIZE - 1, y + PIXEL_SIZE - 1], fill=color)

    return img

def upload_to_s3(img):
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    key = f"snapshots/canvas_{int(time.time())}.png"
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=buffer,
        ContentType="image/png"
    )

    url = f"https://{BUCKET_NAME}.s3.eu-west-1.amazonaws.com/{key}"
    return url

def send_discord_response(app_id, token, image_url, pixel_count):
    url = f"https://discord.com/api/v10/webhooks/{app_id}/{token}"
    payload = {
        "embeds": [{
            "title": "🎨 Canvas Snapshot",
            "description": f"**{pixel_count}** pixels dessinés",
            "image": {"url": image_url},
            "color": 5814783,
            "footer": {"text": "Pixel Canvas"}
        }]
    }
    requests.post(url, json=payload)

def lambda_handler(event, context):
    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])

            if message.get("command") != "canvas":
                continue

            app_id = message["application_id"]
            token  = message["interaction_token"]

            # Récupérer tous les pixels
            pixels = get_all_pixels()
            print(f"Generating snapshot with {len(pixels)} pixels")

            # Générer l'image
            img = generate_image(pixels)

            # Upload sur S3
            image_url = upload_to_s3(img)
            print(f"Snapshot uploaded: {image_url}")

            # Répondre à Discord
            send_discord_response(app_id, token, image_url, len(pixels))

        except Exception as e:
            print(f"Snapshot error: {e}")
            raise

    return {"statusCode": 200}