import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.maintenance import cleanup_legacy_state, get_legacy_state  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or clean legacy backend state")
    parser.add_argument("--app-config", action="store_true", help="Remove legacy app_config keys")
    parser.add_argument("--temp-cookies", action="store_true", help="Remove legacy temp_cookies.txt")
    parser.add_argument("--downloads-zip", action="store_true", help="Remove legacy downloads.zip")
    parser.add_argument("--all", action="store_true", help="Clean all supported legacy items")
    args = parser.parse_args()

    if args.all:
        args.app_config = True
        args.temp_cookies = True
        args.downloads_zip = True

    if not any([args.app_config, args.temp_cookies, args.downloads_zip]):
        state = await get_legacy_state()
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return

    result = await cleanup_legacy_state(
        cleanup_app_config=args.app_config,
        cleanup_temp_cookies=args.temp_cookies,
        cleanup_downloads_zip=args.downloads_zip,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
