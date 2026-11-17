"""Build a Teams sideload package from real deployment values, without provisioning."""

import argparse
import io
import json
import math
import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageDraw


def https_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("A real public HTTPS URL is required.")
    return value


def icon(size: int, outline: bool) -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0) if outline else "#09162b")
    draw = ImageDraw.Draw(image)
    color = "white" if outline else "#8edddc"
    width = max(1, size // 32)
    draw.ellipse((size * 0.14, size * 0.14, size * 0.86, size * 0.86), outline=color, width=width)
    points = []
    for index in range(8):
        angle = index * math.pi / 4
        radius = size * (0.3 if index % 2 == 0 else 0.09)
        points.append((size / 2 + math.sin(angle) * radius, size / 2 - math.cos(angle) * radius))
    draw.polygon(points, fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-id", required=True, type=uuid.UUID)
    parser.add_argument("--app-id", required=True, type=uuid.UUID)
    parser.add_argument("--asset-base-url", required=True, type=https_url)
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--developer-name", required=True)
    parser.add_argument("--website-url", required=True, type=https_url)
    parser.add_argument("--privacy-url", required=True, type=https_url)
    parser.add_argument("--terms-url", required=True, type=https_url)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9]{3,24}", args.storage_account):
        parser.error("--storage-account must be an Azure Storage account name.")
    values = {
        "__BOT_ID__": str(args.bot_id),
        "__APP_ID__": str(args.app_id),
        "__DEVELOPER_NAME__": args.developer_name,
        "__WEBSITE_URL__": args.website_url,
        "__PRIVACY_URL__": args.privacy_url,
        "__TERMS_URL__": args.terms_url,
        "__ASSET_HOST__": urlsplit(args.asset_base_url).hostname,
        "__STORAGE_HOST__": f"{args.storage_account}.blob.core.windows.net",
    }
    template = Path(__file__).resolve().parents[1] / "m365sideloadmanifest/manifest.template.json"
    document = template.read_text(encoding="utf-8")
    for marker, value in values.items():
        document = document.replace(json.dumps(marker), json.dumps(value, ensure_ascii=True))
    manifest = json.loads(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=True, indent=2))
        package.writestr("color.png", icon(192, False))
        package.writestr("outline.png", icon(32, True))
    print(f"Teams package: {args.output.resolve()}")


if __name__ == "__main__":
    main()
