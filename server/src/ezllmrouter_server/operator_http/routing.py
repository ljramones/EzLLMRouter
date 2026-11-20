"""Indexed operator routes and their authorization stages.

Resolve a request once; never discover routes by executing handlers. Exact paths
take precedence over families, then the longest family prefix wins. Family
handlers validate resource IDs, actions and selectors before doing any work.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Literal

from .assets import ASSETS

Stage = Literal[
    "asset",
    "session",
    "account",
    "resource",
    "activity",
    "login",
    "account_write",
    "operation",
    "delete",
]
Dependency = Literal["accounts", "local_connectors", "registry", "successor_store"]


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: str
    stage: Stage
    family: bool = False
    query: bool = True
    requires: Dependency | None = None

    @property
    def failure_event(self) -> str:
        # Only constant route metadata enters an event name, never a request URL.
        return "operator_http." + self.handler + ".failed"


class Router:
    def __init__(self, routes: Iterable[Route]) -> None:
        self.exact: dict[tuple[str, str], Route] = {}
        families: dict[tuple[str, str], Route] = {}
        for route in routes:
            target = families if route.family else self.exact
            key = (route.method, route.path)
            if key in target:
                raise ValueError("duplicate operator route")
            target[key] = route
        self.families = tuple(sorted(families.values(), key=lambda r: -len(r.path)))

    def resolve(
        self, method: str, path: str, *, query: bool, available: Collection[str]
    ) -> Route | None:
        def enabled(route: Route) -> bool:
            return (route.query or not query) and (
                route.requires is None or route.requires in available
            )

        exact = self.exact.get((method, path))
        if exact is not None and enabled(exact):
            return exact
        for route in self.families:
            if route.method == method and path.startswith(route.path) and enabled(route):
                return route
        return None


ROUTES = (
    *(Route("GET", path, "get_assets", "asset", query=False) for path in ASSETS),
    Route("GET", "/operator/v1/session", "get_operator_v1_session", "session", query=False),
    Route(
        "GET",
        "/operator/v1/local-connectors",
        "get_operator_v1_local_connectors",
        "account",
        query=False,
        requires="local_connectors",
    ),
    Route(
        "GET",
        "/operator/v1/local-connectors/availability",
        "get_operator_v1_local_connectors_availability",
        "account",
        query=False,
        requires="local_connectors",
    ),
    Route(
        "GET",
        "/operator/v1/local-connectors/nearby",
        "get_operator_v1_local_connectors_nearby",
        "account",
        query=False,
        requires="local_connectors",
    ),
    Route(
        "GET",
        "/operator/v1/local-connectors/",
        "get_local_connector",
        "account",
        family=True,
        query=False,
        requires="local_connectors",
    ),
    Route(
        "GET",
        "/operator/v1/users",
        "get_operator_v1_users",
        "account",
        query=False,
        requires="accounts",
    ),
    Route(
        "GET",
        "/operator/v1/users/",
        "get_user",
        "account",
        family=True,
        query=False,
        requires="accounts",
    ),
    Route(
        "GET",
        "/operator/v1/integration/vega-me",
        "get_operator_v1_integration_vega_me",
        "account",
        query=False,
    ),
    Route(
        "GET", "/operator/v1/mach33-demo/", "get_operator_v1_mach33_demo", "account", family=True
    ),
    Route(
        "GET",
        "/operator/v1/integration/",
        "get_operator_v1_integration",
        "account",
        family=True,
        requires="registry",
    ),
    Route(
        "GET",
        "/operator/v1/dev12-usage",
        "get_operator_v1_dev12_usage",
        "resource",
        requires="successor_store",
    ),
    Route("GET", "/operator/v1/demo-workspace", "get_operator_v1_demo_workspace", "resource"),
    Route(
        "GET",
        "/operator/v1/usage-costs",
        "get_operator_v1_usage_costs",
        "resource",
        requires="registry",
    ),
    *(
        Route("GET", path, "get_registry_resource", "resource", family=family, requires="registry")
        for path, family in (
            ("/operator/v1/models", True),
            ("/operator/v1/principals", True),
            ("/operator/v1/connections", True),
            ("/operator/v1/provider-validations/", True),
            ("/operator/v1/personal-campaign", False),
            ("/operator/v1/providers", False),
            ("/operator/v1/access/explain", False),
        )
    ),
    Route("GET", "/operator/v1/overview", "get_operator_v1_overview", "activity", query=False),
    Route("GET", "/operator/v1/activity", "get_operator_v1_activity", "activity"),
    Route(
        "GET", "/operator/v1/activity/", "get_activity_detail", "activity", family=True, query=False
    ),
    Route("GET", "/operator/v1/usage", "get_operator_v1_usage", "activity"),
    Route("GET", "/operator/v1/config", "get_operator_v1_config", "activity", query=False),
    Route("GET", "/operator/v1/build", "get_operator_v1_build", "activity", query=False),
    Route(
        "GET",
        "/operator/v1/launch/",
        "get_operator_v1_launch",
        "activity",
        family=True,
        query=False,
    ),
    Route("POST", "/operator/v1/login", "post_operator_v1_login", "login"),
    Route("POST", "/operator/v1/users", "post_operator_v1_users", "account_write"),
    Route("POST", "/operator/v1/account/password", "post_operator_v1_users", "account_write"),
    Route("POST", "/operator/v1/users/", "post_operator_v1_users", "account_write", family=True),
    Route(
        "POST",
        "/operator/v1/local-connectors",
        "post_operator_v1_local_connectors",
        "account_write",
    ),
    Route(
        "POST",
        "/operator/v1/local-connectors/",
        "post_operator_v1_local_connectors",
        "account_write",
        family=True,
    ),
    Route(
        "POST",
        "/operator/v1/integration/",
        "post_operator_v1_integration",
        "account_write",
        family=True,
        requires="registry",
    ),
    Route("POST", "/operator/v1/logout", "post_operator_v1_logout", "operation"),
    *(
        Route("POST", "/operator/v1/" + path, handler, "operation", requires="registry")
        for path, handler in (
            ("registry", "post_operator_v1_registry"),
            ("personal-campaign", "post_operator_v1_personal_campaign"),
            ("provider-credential", "post_operator_v1_provider_credential"),
            ("provider-probe", "post_operator_v1_provider_probe"),
            ("provider-validation", "post_operator_v1_provider_validation"),
            ("provision", "post_operator_v1_provision"),
        )
    ),
    Route("POST", "/operator/v1/demos/", "post_operator_v1_demos", "operation", family=True),
    Route("DELETE", "/operator/v1/users/", "delete_user", "delete", family=True),
    Route(
        "DELETE", "/operator/v1/local-connectors/", "delete_local_connector", "delete", family=True
    ),
)

ROUTER = Router(ROUTES)
