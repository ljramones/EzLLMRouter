"""The public asset allowlist; filesystem contents never create public routes."""

from __future__ import annotations
from collections.abc import Mapping
from urllib.parse import SplitResult
from .context import OperatorContext


from types import MappingProxyType

ASSETS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/integration": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/users_view.js": ("users_view.js", "text/javascript; charset=utf-8"),
        "/local_connectors_view.js": ("local_connectors_view.js", "text/javascript; charset=utf-8"),
        "/integration_view.js": ("integration_view.js", "text/javascript; charset=utf-8"),
        "/integration_console.js": ("integration_console.js", "text/javascript; charset=utf-8"),
        "/integration_accounting.js": (
            "integration_accounting.js",
            "text/javascript; charset=utf-8",
        ),
        "/catalogue_view.js": ("catalogue_view.js", "text/javascript; charset=utf-8"),
        "/activity_usage_view.js": ("activity_usage_view.js", "text/javascript; charset=utf-8"),
        "/crud_view.js": ("crud_view.js", "text/javascript; charset=utf-8"),
        "/providers_view.js": ("providers_view.js", "text/javascript; charset=utf-8"),
        "/source_pages.js": ("source_pages.js", "text/javascript; charset=utf-8"),
        "/usage_costs_view.js": ("usage_costs_view.js", "text/javascript; charset=utf-8"),
        "/demo_workspace_view.js": ("demo_workspace_view.js", "text/javascript; charset=utf-8"),
        "/demo_workspace_team_view.js": (
            "demo_workspace_team_view.js",
            "text/javascript; charset=utf-8",
        ),
        "/scripted_demo_view.js": ("scripted_demo_view.js", "text/javascript; charset=utf-8"),
        "/app.css": ("app.css", "text/css; charset=utf-8"),
        "/integration_console.css": ("integration_console.css", "text/css; charset=utf-8"),
    }
)


class AssetsRoutes:
    def get_assets(
        self: OperatorContext, path: SplitResult, session: None, body: None, scope: str | None
    ) -> None:
        filename, content_type = ASSETS[path.path]
        return self._send(
            200, (self.application.root / filename).read_bytes(), content_type=content_type
        )
