import json
import os
import time
import boto3
import requests
import jwt  # PyJWT

secretsmanager = boto3.client("secretsmanager", region_name="eu-west-1")

DISCORD_API     = "https://discord.com/api/v10"
APP_ID          = os.environ["DISCORD_APP_ID"]
REDIRECT_URI    = os.environ["REDIRECT_URI"]
JWT_SECRET      = os.environ["JWT_SECRET"]

_client_secret_cache = None

def get_client_secret():
    global _client_secret_cache
    if _client_secret_cache is None:
        r = secretsmanager.get_secret_value(SecretId="discord/client-secret")
        _client_secret_cache = r["SecretString"]
    return _client_secret_cache

def exchange_code(code):
    """Échange le code OAuth2 contre un access token Discord."""
    data = {
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(
        f"{DISCORD_API}/oauth2/token",
        data=data,
        headers=headers,
        auth=(APP_ID, get_client_secret())
    )
    r.raise_for_status()
    return r.json()

def get_discord_user(access_token):
    """Récupère le profil Discord de l'utilisateur."""
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(f"{DISCORD_API}/users/@me", headers=headers)
    r.raise_for_status()
    return r.json()

def create_jwt(user):
    """Crée un JWT custom avec les infos Discord."""
    payload = {
        "sub":      user["id"],
        "username": user["username"],
        "avatar":   user.get("avatar"),
        "iat":      int(time.time()),
        "exp":      int(time.time()) + 86400  # 24h
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def lambda_handler(event, context):
    path   = event.get("rawPath", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    params = event.get("queryStringParameters", {}) or {}

    # CORS preflight
    cors_headers = {
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
    }

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": cors_headers, "body": ""}

    # GET /auth/login → redirect vers Discord OAuth2
    if path == "/auth/login":
        scope = "identify"
        discord_url = (
            f"https://discord.com/oauth2/authorize"
            f"?client_id={APP_ID}"
            f"&redirect_uri={requests.utils.quote(REDIRECT_URI)}"
            f"&response_type=code"
            f"&scope={scope}"
        )
        return {
            "statusCode": 302,
            "headers": {**cors_headers, "Location": discord_url},
            "body": ""
        }

    # GET /auth/callback → échange code → JWT
    if path == "/auth/callback":
        code = params.get("code")
        if not code:
            return {
                "statusCode": 400,
                "headers": cors_headers,
                "body": json.dumps({"error": "Missing code"})
            }
        try:
            token_data = exchange_code(code)
            user       = get_discord_user(token_data["access_token"])
            jwt_token  = create_jwt(user)

            # Redirect vers le frontend avec le token en query param
            frontend_url = os.environ.get("FRONTEND_URL", "")
            return {
                "statusCode": 302,
                "headers": {
                    **cors_headers,
                    "Location": f"{frontend_url}#token={jwt_token}"
                },
                "body": ""
            }
        except Exception as e:
            print(f"Auth error: {e}")
            return {
                "statusCode": 500,
                "headers": cors_headers,
                "body": json.dumps({"error": str(e)})
            }

    # GET /auth/me → vérifie le JWT et retourne le profil
    if path == "/auth/me":
        auth_header = event.get("headers", {}).get("authorization", "")
        token = auth_header.replace("Bearer ", "")
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            return {
                "statusCode": 200,
                "headers": cors_headers,
                "body": json.dumps(payload)
            }
        except jwt.ExpiredSignatureError:
            return {"statusCode": 401, "headers": cors_headers, "body": json.dumps({"error": "Token expired"})}
        except Exception:
            return {"statusCode": 401, "headers": cors_headers, "body": json.dumps({"error": "Invalid token"})}

    return {"statusCode": 404, "body": json.dumps({"error": "Not found"})}