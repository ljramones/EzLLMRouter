"""Shared operator HTTP types and strict wire helpers."""

from __future__ import annotations
from ..observability import log_failure
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import cookies
from http.client import HTTPConnection
from ..http_server import BoundedHTTPServer as ThreadingHTTPServer, SafeHTTPRequestHandler
import csv
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit
from ..registry import RegistryConflict
from ..provider_adapters import ADAPTERS, PROVIDERS
from ..reporting import usage_costs
from ..successor_reporting import usage_report
from ..demo_workspace import project_demo
from ..demo_workspace_team import project_team_demo
from ..integration_accounting import IntegrationError, route_id
from ..user_management import UserManager, UserError, LoginThrottle, ROLE_PERMISSIONS
from ..local_connectors import LocalConnectors, ConnectorError


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate operator key")
        value[key] = item
    return value


def _reject_number(_text):
    raise ValueError("unsupported operator number")


SESSION_SECONDS = 1800
NOT_HANDLED = object()

# Explicit exports consumed by the operator route modules.
__all__ = [
    "ADAPTERS",
    "ConnectorError",
    "HTTPConnection",
    "IntegrationError",
    "LocalConnectors",
    "LoginThrottle",
    "NOT_HANDLED",
    "PROVIDERS",
    "Path",
    "ROLE_PERMISSIONS",
    "RegistryConflict",
    "SESSION_SECONDS",
    "SafeHTTPRequestHandler",
    "ThreadPoolExecutor",
    "ThreadingHTTPServer",
    "UserError",
    "UserManager",
    "cookies",
    "csv",
    "datetime",
    "hmac",
    "io",
    "json",
    "log_failure",
    "os",
    "parse_qs",
    "project_demo",
    "project_team_demo",
    "route_id",
    "secrets",
    "socket",
    "socketserver",
    "threading",
    "time",
    "timezone",
    "urlsplit",
    "usage_costs",
    "usage_report",
    "uuid",
]
