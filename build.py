"""Build v2ray geosite.dat and geoip.dat for the Starlit Happ profile."""

import ipaddress
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RELEASE = ROOT / "release"


def encode_varint(number):
    out = bytearray()
    while True:
        piece = number & 0x7F
        number >>= 7
        if number:
            out.append(piece | 0x80)
        else:
            out.append(piece)
            return bytes(out)


def field_bytes(field_number, payload):
    key = (field_number << 3) | 2
    return encode_varint(key) + encode_varint(len(payload)) + payload


def field_string(field_number, text):
    return field_bytes(field_number, text.encode("utf-8"))


def field_varint(field_number, number):
    key = (field_number << 3) | 0
    return encode_varint(key) + encode_varint(number)


def read_domains(path):
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line.startswith("domain:"):
            line = line[len("domain:") :].strip()
        if not line or line.startswith("include:") or " " in line or "/" in line:
            continue
        found.append(line.rstrip("."))
    return found


def unique(items):
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "starlit-routing"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def encode_domain(kind, value):
    # 0 plain, 1 regex, 2 domain (this name and every subdomain), 3 full
    return field_varint(1, kind) + field_string(2, value)


def encode_site(code, domains):
    body = field_string(1, code.upper())
    for domain in domains:
        body += field_bytes(2, encode_domain(2, domain))
    return body


def encode_geosite(categories):
    body = b""
    for code, domains in categories:
        body += field_bytes(1, encode_site(code, domains))
    return body


def encode_cidr(network):
    packed = network.network_address.packed
    return field_bytes(1, packed) + field_varint(2, network.prefixlen)


def encode_geoip_entry(code, networks):
    body = field_string(1, code.upper())
    for network in networks:
        body += field_bytes(2, encode_cidr(network))
    return body


def encode_geoip(categories):
    body = b""
    for code, networks in categories:
        body += field_bytes(1, encode_geoip_entry(code, networks))
    return body


def parse_cidrs(text):
    networks = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        networks.append(ipaddress.ip_network(line, strict=False))
    return networks


def main():
    DATA.mkdir(exist_ok=True)
    RELEASE.mkdir(exist_ok=True)
    gov_text = download(
        "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/category-gov-ru"
    )
    (DATA / "category-gov-ru.txt").write_text(gov_text, encoding="utf-8")

    direct = ["ru", "su", "xn--p1ai"]
    for name in ("direct-extra.txt", "category-gov-ru.txt"):
        direct.extend(read_domains(DATA / name))
    direct = unique(direct)
    (DATA / "direct-domains.txt").write_text("\n".join(direct) + "\n", encoding="utf-8")

    categories = [
        ("DIRECT", direct),
        ("PRIVATE", read_domains(DATA / "private.txt")),
        ("YOUTUBE", read_domains(DATA / "youtube.txt")),
        ("GOOGLE-PLAY", read_domains(DATA / "google-play.txt")),
        ("GOOGLE-DEEPMIND", read_domains(DATA / "google-deepmind.txt")),
    ]
    geosite = encode_geosite(categories)
    (RELEASE / "geosite.dat").write_bytes(geosite)

    ip_dir = DATA / "ip"
    ip_dir.mkdir(exist_ok=True)
    sources = {
        "ru-ipv4.txt": "https://www.ipdeny.com/ipblocks/data/countries/ru.zone",
        "by-ipv4.txt": "https://www.ipdeny.com/ipblocks/data/countries/by.zone",
        "ru-ipv6.txt": "https://www.ipdeny.com/ipv6/ipaddresses/blocks/ru.zone",
        "by-ipv6.txt": "https://www.ipdeny.com/ipv6/ipaddresses/blocks/by.zone",
    }
    direct_ips = []
    for name, url in sources.items():
        text = download(url)
        (ip_dir / name).write_text(text, encoding="utf-8")
        direct_ips.extend(parse_cidrs(text))
    private_ips = parse_cidrs((DATA / "private-ip.txt").read_text(encoding="utf-8"))
    geoip = encode_geoip([("DIRECT", direct_ips), ("PRIVATE", private_ips)])
    (RELEASE / "geoip.dat").write_bytes(geoip)
    print("geosite", len(geosite), "domains", len(direct))
    print("geoip", len(geoip), "cidrs", len(direct_ips), "private", len(private_ips))


if __name__ == "__main__":
    main()
