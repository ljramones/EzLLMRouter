"""Operator assets handlers."""

from .common import NOT_HANDLED


class AssetsRoutes:
    def get_assets(self, path, session, body, scope):
        if path.path in (
            "/",
            "/integration",
            "/app.js",
            "/users_view.js",
            "/local_connectors_view.js",
            "/catalogue_view.js",
            "/activity_usage_view.js",
            "/crud_view.js",
            "/providers_view.js",
            "/source_pages.js",
            "/usage_costs_view.js",
            "/demo_workspace_view.js",
            "/demo_workspace_team_view.js",
            "/mach33_demo_view.js",
            "/integration_view.js",
            "/integration_console.js",
            "/integration_accounting.js",
            "/app.css",
            "/integration_console.css",
        ) and (not path.query):
            filename, content_type = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/integration": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/users_view.js": ("users_view.js", "text/javascript; charset=utf-8"),
                "/local_connectors_view.js": (
                    "local_connectors_view.js",
                    "text/javascript; charset=utf-8",
                ),
                "/integration_view.js": ("integration_view.js", "text/javascript; charset=utf-8"),
                "/integration_console.js": (
                    "integration_console.js",
                    "text/javascript; charset=utf-8",
                ),
                "/integration_accounting.js": (
                    "integration_accounting.js",
                    "text/javascript; charset=utf-8",
                ),
                "/catalogue_view.js": ("catalogue_view.js", "text/javascript; charset=utf-8"),
                "/activity_usage_view.js": (
                    "activity_usage_view.js",
                    "text/javascript; charset=utf-8",
                ),
                "/crud_view.js": ("crud_view.js", "text/javascript; charset=utf-8"),
                "/providers_view.js": ("providers_view.js", "text/javascript; charset=utf-8"),
                "/source_pages.js": ("source_pages.js", "text/javascript; charset=utf-8"),
                "/usage_costs_view.js": ("usage_costs_view.js", "text/javascript; charset=utf-8"),
                "/demo_workspace_view.js": (
                    "demo_workspace_view.js",
                    "text/javascript; charset=utf-8",
                ),
                "/demo_workspace_team_view.js": (
                    "demo_workspace_team_view.js",
                    "text/javascript; charset=utf-8",
                ),
                "/mach33_demo_view.js": ("mach33_demo_view.js", "text/javascript; charset=utf-8"),
                "/app.css": ("app.css", "text/css; charset=utf-8"),
                "/integration_console.css": ("integration_console.css", "text/css; charset=utf-8"),
            }[path.path]
            return self._send(
                200, (self.application.root / filename).read_bytes(), content_type=content_type
            )
        return NOT_HANDLED
