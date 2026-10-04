"""Local deployment: live previews of generated apps.

Static apps are served by a hardened static server; backend apps run as a
sandboxed uvicorn subprocess (scrubbed environment, localhost only) with a
persistent preview database.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Settings
from .log import get_logger
from .verification.servers import BackendProcess, StaticServer

log = get_logger("deploy")


class PreviewManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._servers: dict[str, StaticServer | BackendProcess] = {}
        self._urls: dict[str, str] = {}

    async def start(self, project_id: str, root: Path, backend: bool) -> str:
        await self.stop(project_id)
        if backend:
            if not self.settings.run_generated_backends:
                raise RuntimeError("running generated backends is disabled (AICEO_RUN_GENERATED_BACKENDS=false)")
            art = self.settings.artifacts_dir / project_id
            proc = BackendProcess(root, art / "preview.log", db_path=art / "preview.db", fresh_db=False)
            url = await asyncio.to_thread(proc.start) + "/"
            self._servers[project_id] = proc
        else:
            srv = StaticServer(root).start()
            url = srv.url + "/"
            self._servers[project_id] = srv
        self._urls[project_id] = url
        log.info("preview for %s at %s", project_id, url)
        return url

    async def stop(self, project_id: str) -> bool:
        server = self._servers.pop(project_id, None)
        self._urls.pop(project_id, None)
        if server is None:
            return False
        await asyncio.to_thread(server.stop)
        return True

    def url(self, project_id: str) -> str | None:
        server = self._servers.get(project_id)
        if isinstance(server, BackendProcess) and not server.running():
            return None
        return self._urls.get(project_id)

    async def stop_all(self) -> None:
        for pid in list(self._servers):
            await self.stop(pid)
