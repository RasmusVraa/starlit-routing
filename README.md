# Starlit routing

Свои базы для Happ: российские сайты и IP идут напрямую, YouTube и Google остаются через VPN.

## Файлы

- `release/geosite.dat` — домены
- `release/geoip.dat` — сети России, Беларуси и локальные адреса

Категории geosite: `direct`, `ads`, `private`, `youtube`, `google-play`, `google-deepmind`.

Категории geoip: `direct`, `private`.

`geosite:direct` включает зоны `.ru`, `.su`, `.рф` и отдельные домены сервисов, которые не открываются с VPN (банки, Госуслуги, Яндекс, VK, Ozon и их CDN). `geoip:direct` — публичные сети RU и BY с [ipdeny.com](https://www.ipdeny.com/ipblocks/).

## CDN

```
https://gcore.jsdelivr.net/gh/RasmusVraa/starlit-routing@v2/release/geosite.dat
https://gcore.jsdelivr.net/gh/RasmusVraa/starlit-routing@v2/release/geoip.dat
```

## Сборка

```
python build.py
```
