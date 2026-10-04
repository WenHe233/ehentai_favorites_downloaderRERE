from pathlib import Path
from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Only client routes receive the SPA shell. Missing API/assets remain 404.
            normalized = path.replace("\\", "/").lstrip("/")
            if exc.status_code == 404 and scope["method"] in {"GET", "HEAD"} and not normalized.startswith(("api/", "assets/")) and not Path(normalized).suffix:
                return await super().get_response("index.html", scope)
            raise
