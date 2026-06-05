import argparse
import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def local_ipv4_addresses():
    addresses = {"127.0.0.1"}
    hostname = socket.gethostname()
    try:
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addresses.add(item[4][0])
    except socket.gaierror:
        pass
    return sorted(addresses)


def parse_sans(values):
    names = {"localhost", socket.gethostname()}
    ips = set(local_ipv4_addresses())

    for value in values:
        value = value.strip()
        if not value:
            continue
        try:
            ips.add(str(ipaddress.ip_address(value)))
        except ValueError:
            names.add(value)

    return sorted(names), sorted(ips)


def main():
    parser = argparse.ArgumentParser(description="Generate a local HTTPS self-signed certificate.")
    parser.add_argument("--out-dir", default="certs", help="Output directory for server.crt/server.key")
    parser.add_argument("--days", type=int, default=825, help="Certificate validity days")
    parser.add_argument("--san", action="append", default=[], help="Extra DNS name or IP address")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cert_path = out_dir / "server.crt"
    key_path = out_dir / "server.key"

    dns_names, ip_addresses = parse_sans(args.san)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AI Interview Local Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0] if dns_names else "localhost"),
    ])

    san_values = [x509.DNSName(name) for name in dns_names]
    san_values.extend(x509.IPAddress(ipaddress.ip_address(ip)) for ip in ip_addresses)

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=max(args.days, 1)))
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=True,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False,
        ), critical=True)
        .sign(private_key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))

    print(f"Generated certificate: {cert_path}")
    print(f"Generated private key: {key_path}")
    print("Included DNS names:", ", ".join(dns_names))
    print("Included IP addresses:", ", ".join(ip_addresses))
    print()
    print("LAN users should open one of these HTTPS URLs and trust/import certs/server.crt if prompted:")
    for ip in ip_addresses:
        print(f"  https://{ip}:8000/api/ai-interview/hr/")


if __name__ == "__main__":
    main()
