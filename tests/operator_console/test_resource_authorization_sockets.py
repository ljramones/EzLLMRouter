"""Existing operator resource scenarios through real HTTP socket parsing."""

from tests.operator_console import test_authorization_matrix_sockets as transport
from tests.operator_console import test_resource_authorization as matrix


class SocketResourceAuthorizationTests(matrix.ResourceAuthorizationTests):
    exchange = transport.SocketPairAuthorizationMatrixTests.exchange
