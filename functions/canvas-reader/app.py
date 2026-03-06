import json
import boto3

dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")
canvas_table = dynamodb.Table("canvas-pixels")

def get_chunks():
    """Scan tous les chunks existants."""
    response = canvas_table.scan()
    items = response.get("Items", [])

    # Pagination si > 1MB de données
    while "LastEvaluatedKey" in response:
        response = canvas_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    return items

def lambda_handler(event, context):
    try:
        items = get_chunks()

        pixels = []
        for item in items:
            pixels.append({
                "x":          int(item["x"]),
                "y":          int(item["y"]),
                "color":      item["color"],
                "author_id":  item["author_id"],
                "author_name": item.get("author_name", item["author_id"]),
                "updated_at": item["updated_at"]
            })

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"pixels": pixels, "count": len(pixels)})
        }

    except Exception as e:
        print(f"Error reading canvas: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }