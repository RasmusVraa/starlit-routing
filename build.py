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
    return parse_domain_lines(path.read_text(encoding="utf-8"))


def parse_domain_lines(text):
    found = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line.startswith("domain:"):
            line = line[len("domain:") :].strip()
        if line.startswith(("0.0.0.0", "127.0.0.1")):
            parts = line.split()
            if len(parts) >= 2:
                line = parts[1]
        if not line or line.startswith(("include:", "!", "||")) or " " in line or "/" in line:
            continue
        if line.startswith("*."):
            line = line[2:]
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
    for kind, domain in domains:
        body += field_bytes(2, encode_domain(kind, domain))
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


def read_varint(buf, index):
    number = 0
    shift = 0
    while True:
        byte = buf[index]
        index += 1
        number |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return number, index
        shift += 7


def parse_fields(buf):
    index = 0
    fields = []
    while index < len(buf):
        key, index = read_varint(buf, index)
        wire = key & 7
        field = key >> 3
        if wire == 0:
            value, index = read_varint(buf, index)
        elif wire == 2:
            length, index = read_varint(buf, index)
            value = buf[index : index + length]
            index += length
        elif wire == 5:
            value = buf[index : index + 4]
            index += 4
        elif wire == 1:
            value = buf[index : index + 8]
            index += 8
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        fields.append((field, wire, value))
    return fields


def cached_dat(name, url):
    path = DATA / "cache" / name
    if path.exists() and path.stat().st_size > 1000:
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "starlit-routing"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    path.write_bytes(data)
    return data


def load_geosite(names):
    picked = {name: [] for name in names}
    for filename, url in (
        (
            "loyalsoldier-geosite.dat",
            "https://gcore.jsdelivr.net/gh/Loyalsoldier/v2ray-rules-dat@release/geosite.dat",
        ),
        (
            "roscom-geosite.dat",
            "https://gcore.jsdelivr.net/gh/hydraponique/roscomvpn-geosite@release/geosite.dat",
        ),
    ):
        for field, wire, value in parse_fields(cached_dat(filename, url)):
            if field != 1 or wire != 2:
                continue
            code = ""
            domains = []
            for inner, inner_wire, inner_value in parse_fields(value):
                if inner == 1 and inner_wire == 2:
                    code = inner_value.decode("utf-8", "replace").upper()
                elif inner == 2 and inner_wire == 2:
                    kind = 2
                    domain = ""
                    for part, part_wire, part_value in parse_fields(inner_value):
                        if part == 1 and part_wire == 0:
                            kind = part_value
                        elif part == 2 and part_wire == 2:
                            domain = part_value.decode("utf-8", "replace").strip().lower()
                    if domain:
                        domains.append((kind, domain))
            if code in picked:
                picked[code].extend(domains)
    return picked


def decode_cidr(blob):
    address = b""
    prefix = None
    for field, wire, value in parse_fields(blob):
        if field == 1 and wire == 2:
            address = value
        elif field == 2 and wire == 0:
            prefix = value
    if prefix is None or len(address) not in (4, 16):
        return None
    text = ".".join(str(piece) for piece in address) if len(address) == 4 else str(ipaddress.IPv6Address(address))
    return ipaddress.ip_network(f"{text}/{prefix}", strict=False)


def load_geoip(names):
    picked = {name: [] for name in names}
    for filename, url in (
        (
            "loyalsoldier-geoip.dat",
            "https://gcore.jsdelivr.net/gh/Loyalsoldier/v2ray-rules-dat@release/geoip.dat",
        ),
        (
            "roscom-geoip.dat",
            "https://gcore.jsdelivr.net/gh/hydraponique/roscomvpn-geoip@release/geoip.dat",
        ),
    ):
        for field, wire, value in parse_fields(cached_dat(filename, url)):
            if field != 1 or wire != 2:
                continue
            code = ""
            networks = []
            for inner, inner_wire, inner_value in parse_fields(value):
                if inner == 1 and inner_wire == 2:
                    code = inner_value.decode("utf-8", "replace").upper()
                elif inner == 2 and inner_wire == 2:
                    network = decode_cidr(inner_value)
                    if network is not None:
                        networks.append(network)
            if code in picked:
                picked[code].extend(networks)
    return picked


def unique_domains(items):
    seen = set()
    result = []
    for kind, domain in items:
        key = (kind, domain)
        if domain and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def unique_networks(items):
    seen = set()
    result = []
    for network in items:
        key = (network.version, int(network.network_address), network.prefixlen)
        if key not in seen:
            seen.add(key)
            result.append(network)
    return result


def main():
    DATA.mkdir(exist_ok=True)
    RELEASE.mkdir(exist_ok=True)
    gov_text = download(
        "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/category-gov-ru"
    )
    (DATA / "category-gov-ru.txt").write_text(gov_text, encoding="utf-8")

    imported = load_geosite(
        [
            "OZON",
            "WILDBERRIES",
            "CATEGORY-BANK-RU",
            "CATEGORY-ECOMMERCE-RU",
            "CATEGORY-RETAIL-RU",
            "CATEGORY-GOV-RU",
            "SBER",
            "SBERBANK",
            "TBANK-RU",
            "TLD-RU",
            "CATEGORY-RU",
            "YANDEX",
            "WHITELIST",
            "PRIVATE",
        ]
    )
    shops = [(2, domain) for domain in read_domains(DATA / "shops.txt")]
    extras = []
    for name in ("direct-extra.txt", "category-gov-ru.txt"):
        extras.extend((2, domain) for domain in read_domains(DATA / name))
    zones = [(1, r".*\.ru$"), (1, r".*\.su$"), (1, r".*\.xn--p1ai$"), (2, "ru"), (2, "su"), (2, "xn--p1ai")]
    direct = unique_domains(
        [
            *zones,
            *shops,
            *extras,
            *imported["CATEGORY-RU"],
            *imported["TLD-RU"],
            *imported["OZON"],
            *imported["WILDBERRIES"],
            *imported["CATEGORY-BANK-RU"],
            *imported["CATEGORY-ECOMMERCE-RU"],
            *imported["CATEGORY-RETAIL-RU"],
            *imported["CATEGORY-GOV-RU"],
            *imported["SBER"],
            *imported["SBERBANK"],
            *imported["TBANK-RU"],
            *imported["YANDEX"],
            *imported["WHITELIST"],
        ]
    )
    protected = {domain for kind, domain in direct if kind != 1 and "." in domain}

    def covered(domain, roots):
        return any(domain == root or domain.endswith("." + root) for root in roots)

    ads_text = download("https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=0")
    (DATA / "ads.txt").write_text(ads_text, encoding="utf-8")
    ads = [(2, domain) for domain in unique(parse_domain_lines(ads_text) + read_domains(DATA / "ads-extra.txt"))]
    ads = [(kind, domain) for kind, domain in ads if not covered(domain, protected)]
    (DATA / "direct-domains.txt").write_text("\n".join(domain for _kind, domain in direct) + "\n", encoding="utf-8")

    def typed(names):
        return [(2, domain) for domain in names]

    categories = [
        ("DIRECT", direct),
        ("RU", zones),
        ("TLD-RU", unique_domains([*zones, *imported["TLD-RU"]])),
        ("CATEGORY-RU", direct),
        ("OZON", unique_domains([*imported["OZON"], *shops])),
        ("WILDBERRIES", unique_domains([*imported["WILDBERRIES"], *shops])),
        ("CATEGORY-BANK-RU", unique_domains([*imported["CATEGORY-BANK-RU"], *imported["SBER"], *imported["SBERBANK"], *imported["TBANK-RU"], *shops])),
        ("RU-BANKS", unique_domains([*imported["CATEGORY-BANK-RU"], *imported["SBER"], *imported["SBERBANK"], *imported["TBANK-RU"], *shops])),
        ("CATEGORY-ECOMMERCE-RU", unique_domains([*imported["CATEGORY-ECOMMERCE-RU"], *imported["OZON"], *imported["WILDBERRIES"], *shops])),
        ("CATEGORY-RETAIL-RU", unique_domains([*imported["CATEGORY-RETAIL-RU"], *shops])),
        ("CATEGORY-GOV-RU", unique_domains(imported["CATEGORY-GOV-RU"])),
        ("SBER", unique_domains([*imported["SBER"], *imported["SBERBANK"]])),
        ("TBANK-RU", unique_domains(imported["TBANK-RU"])),
        ("YANDEX", unique_domains(imported["YANDEX"])),
        ("WHITELIST", unique_domains(imported["WHITELIST"])),
        ("ADS", ads),
        ("PRIVATE", unique_domains([*typed(read_domains(DATA / "private.txt")), *imported["PRIVATE"]])),
        ("YOUTUBE", typed(read_domains(DATA / "youtube.txt"))),
        ("GOOGLE-PLAY", typed(read_domains(DATA / "google-play.txt"))),
        ("GOOGLE-DEEPMIND", typed(read_domains(DATA / "google-deepmind.txt"))),
    ]
    geosite = encode_geosite(categories)
    (RELEASE / "geosite.dat").write_bytes(geosite)
    wanted = ("ozon.ru", "wildberries.ru", "wb.ru", "sberbank.ru", "tbank.ru", "nspk.ru")
    have = {domain for _kind, domain in direct}
    print("missing", [domain for domain in wanted if domain not in have])

    ip_dir = DATA / "ip"
    ip_dir.mkdir(exist_ok=True)
    sources = {
        "ru-ipv4.txt": "https://www.ipdeny.com/ipblocks/data/aggregated/ru-aggregated.zone",
        "by-ipv4.txt": "https://www.ipdeny.com/ipblocks/data/aggregated/by-aggregated.zone",
        "ru-ipv6.txt": "https://www.ipdeny.com/ipv6/ipaddresses/blocks/ru.zone",
        "by-ipv6.txt": "https://www.ipdeny.com/ipv6/ipaddresses/blocks/by.zone",
    }
    direct_ips = []
    for name, url in sources.items():
        text = download(url)
        (ip_dir / name).write_text(text, encoding="utf-8")
        direct_ips.extend(parse_cidrs(text))
    imported_ips = load_geoip(["RU", "BY", "DIRECT", "WHITELIST", "PRIVATE"])
    direct_ips = unique_networks(
        [
            *direct_ips,
            *imported_ips["RU"],
            *imported_ips["BY"],
            *imported_ips["DIRECT"],
            *imported_ips["WHITELIST"],
        ]
    )
    private_ips = unique_networks(
        parse_cidrs((DATA / "private-ip.txt").read_text(encoding="utf-8")) + imported_ips["PRIVATE"]
    )
    geoip = encode_geoip([("DIRECT", direct_ips), ("RU", direct_ips), ("PRIVATE", private_ips)])
    (RELEASE / "geoip.dat").write_bytes(geoip)
    print("geosite", len(geosite), "direct", len(direct), "ads", len(ads))
    print("geoip", len(geoip), "cidrs", len(direct_ips), "private", len(private_ips))


if __name__ == "__main__":
    main()
