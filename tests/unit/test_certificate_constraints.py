"""Offline regression for wildcard SANs escaping CA DNS name constraints."""

from datetime import datetime, timedelta, timezone
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from cryptography.x509.verification import (
    Criticality,
    ExtensionPolicy,
    PolicyBuilder,
    Store,
    VerificationError,
)


EVALUATION_TIME = datetime(2027, 1, 1, tzinfo=timezone.utc)


def certificate(subject, issuer, key, issuer_key, *, ca, extensions=()):
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(EVALUATION_TIME - timedelta(days=1))
        .not_valid_after(EVALUATION_TIME + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    for extension, critical in extensions:
        builder = builder.add_extension(extension, critical=critical)
    return builder.sign(issuer_key, hashes.SHA256())


class CertificateConstraintTests(unittest.TestCase):
    def verify(self, permitted_name, leaf_name, hostname):
        root_key = ec.generate_private_key(ec.SECP256R1())
        root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Root")])
        root = certificate(root_name, root_name, root_key, root_key, ca=True)
        sub_key = ec.generate_private_key(ec.SECP256R1())
        sub_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Constrained CA")])
        sub = certificate(
            sub_name,
            root_name,
            sub_key,
            root_key,
            ca=True,
            extensions=[
                (
                    x509.NameConstraints(
                        permitted_subtrees=[x509.DNSName(permitted_name)],
                        excluded_subtrees=None,
                    ),
                    True,
                )
            ],
        )
        leaf_key = ec.generate_private_key(ec.SECP256R1())
        leaf_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Leaf")])
        leaf = certificate(
            leaf_subject,
            sub_name,
            leaf_key,
            sub_key,
            ca=False,
            extensions=[(x509.SubjectAlternativeName([x509.DNSName(leaf_name)]), False)],
        )
        ca_policy = ExtensionPolicy.permit_all().require_present(
            x509.BasicConstraints,
            Criticality.AGNOSTIC,
            None,
        )
        leaf_policy = ExtensionPolicy.permit_all().require_present(
            x509.SubjectAlternativeName,
            Criticality.AGNOSTIC,
            None,
        )
        verifier = (
            PolicyBuilder()
            .store(Store([root]))
            .time(EVALUATION_TIME)
            .extension_policies(ca_policy=ca_policy, ee_policy=leaf_policy)
            .build_server_verifier(x509.DNSName(hostname))
        )
        return verifier.verify(leaf, [sub])

    def test_exact_dns_name_within_permitted_subtree_is_accepted(self):
        chain = self.verify("foo.example.com", "foo.example.com", "foo.example.com")
        self.assertEqual(len(chain), 3)

    def test_wildcard_within_permitted_parent_is_accepted(self):
        chain = self.verify("example.com", "*.example.com", "bar.example.com")
        self.assertEqual(len(chain), 3)

    def test_wildcard_cannot_escape_exact_permitted_name(self):
        with self.assertRaises(VerificationError):
            self.verify("foo.example.com", "*.example.com", "bar.example.com")


if __name__ == "__main__":
    unittest.main()
