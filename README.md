# Shotle

Günlük NBA tahmin oyunu. Gizli oyuncunun bölge bazlı şut haritasına bakıp 6 tahminde oyuncuyu bul.

Site tek dosya: `index.html`. Oyuncu verisi ve takvim dosyanın içine gömülü, sunucu ya da derleme adımı gerekmiyor.

## Veriyi yeniden üretmek

```bash
python3 -m venv .venv
.venv/bin/pip install nba_api pandas
.venv/bin/python shotle_data.py --season 2025-26
.venv/bin/python shotle_calendar.py
```

- `shotle_data.py`: `stats.nba.com` verisini çeker, `shotle-data.json` dosyasını yazar ve `index.html` içine gömer. Ham yanıtlar `shotle_cache/` klasöründe saklanır.
- `shotle_calendar.py`: günlük oyuncu takvimini `puzzles.json` dosyasına yazar ve `index.html` içine gömer. Bugüne kadarki günler korunur, gelecek günler yeniden üretilebilir.

Bu proje NBA ile bağlantılı değildir. Veriler NBA'in herkese açık istatistik sayfalarından alınmıştır.
