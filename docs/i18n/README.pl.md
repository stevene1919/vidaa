# Integracja VIDAA Smart TV dla Home Assistant

<p align="center">
  <a href="../../README.md"><img src="https://img.shields.io/badge/🇬🇧_English-gray?style=flat-square" alt="English"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/🇩🇪_Deutsch-gray?style=flat-square" alt="Deutsch"></a>
  <a href="README.it.md"><img src="https://img.shields.io/badge/🇮🇹_Italiano-gray?style=flat-square" alt="Italiano"></a>
  <a href="README.fr.md"><img src="https://img.shields.io/badge/🇫🇷_Français-gray?style=flat-square" alt="Français"></a>
  <a href="README.ru.md"><img src="https://img.shields.io/badge/🇷🇺_Русский-gray?style=flat-square" alt="Русский"></a>
  <a href="README.uk.md"><img src="https://img.shields.io/badge/🇺🇦_Українська-gray?style=flat-square" alt="Українська"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/🇨🇳_简体中文-gray?style=flat-square" alt="简体中文"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/🇪🇸_Español-gray?style=flat-square" alt="Español"></a>
  <a href="README.pl.md"><img src="https://img.shields.io/badge/🇵🇱_Polski-blue?style=flat-square" alt="Polski"></a>
</p>

[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/default)
[![Documentation](https://img.shields.io/badge/docs-stevene.enuff.com-blue.svg)](https://stevene.enuff.com/vidaa)
[![GitHub Release](https://img.shields.io/github/v/release/stevene1919/vidaa)](https://github.com/stevene1919/vidaa/releases)

Natywna integracja Home Assistant dla inteligentnych telewizorów i projektorów z systemem **VIDAA OS** (Hisense, Toshiba, Loewe, Philips, Sharp, JVC, TOPTRO i marek partnerskich).

Łączy się **bezpośrednio** z wewnętrznym brokerem MQTT telewizora (port TLS `36669`) za pomocą certyfikatów klienta, zapewniając natychmiastowe lokalne aktualizacje stanu (push), sterowanie odtwarzaczem multimedialnym, uruchamianie aplikacji, Wake-on-LAN oraz wirtualną nawigację pilotem bez konieczności stosowania zewnętrznych mostków czy chmury.

---

## 🔰 Szybki start (Przewodnik dla początkujących)

Konfiguracja telewizora zajmuje mniej niż 2 minuty w 3 prostych krokach:

### 1️⃣ Instalacja przez Marketplace (HACS)
Kliknij poniższy przycisk (lub wyszukaj **VIDAA Smart TV** w Marketplace (HACS) → Integracje → Pobierz):

[![Otwórz Marketplace (HACS)](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stevene1919&repository=vidaa&category=integration)

### 2️⃣ Certyfikaty klienta (Wygodne przesyłanie w przeglądarce lub ręczne umieszczenie)
Telewizory VIDAA wymagają obustronnego szyfrowania TLS na porcie 36669.
- **✨ Przesyłanie w przeglądarce za 1 kliknięciem (Zalecane):** Podczas konfiguracji Home Assistant automatycznie sprawdza obecność certyfikatów. Jeśli ich brakuje, po prostu prześlij oficjalny pakiet aplikacji mobilnej (`.apk` lub `.xapk`), magazyn kluczy PKCS#12 (`client_mobile_android.p12`, `El.p12`, `3R.p12`, `toshiba.p12`) lub połączony pakiet `.pem` bezpośrednio z poziomu przeglądarki! Home Assistant automatycznie wyodrębni, odszyfruje i bezpiecznie zapisze certyfikaty w pamięci podręcznej.
- **Ręczne umieszczenie i własne ścieżki:** Alternatywnie możesz umieścić pliki `client_mobile_android.p12`, `El.p12`, `3R.p12` lub `hisense.crt` + `hisense.key` w katalogu `/config/ssl/` (automatyczne wykrywanie) lub wybrać ręczne wprowadzenie ścieżek w oknie dialogowym konfiguracji.

> [!TIP]
> **Szukasz szczegółowego przewodnika ze zrzutami ekranu?**  
> Zobacz **[Przewodnik dla początkujących](../quick_start_beginners.md)** (w celu uzyskania zaawansowanych poleceń OpenSSL i niestandardowych kluczy PEM zobacz [Przewodnik SSL](../certificates.md)).

### 3️⃣ Sparuj za pomocą kodu PIN na ekranie
1. Zrestartuj Home Assistant (`Ustawienia` → `System` → `Uruchom ponownie`).
2. Przejdź do **Ustawienia → Urządzenia i usługi → Dodaj integrację** i wyszukaj **VIDAA Smart TV**.
3. Wprowadź lokalny adres IP telewizora i kliknij **Prześlij**.
4. Wpisz **4-cyfrowy kod PIN** wyświetlony na ekranie telewizora, aby zakończyć konfigurację!

> [!IMPORTANT]
> **Wymaganie telewizora — włącz usługi inteligentne / połączone**:  
> Telewizor musi mieć włączone **Usługi inteligentne / połączone** oraz zaakceptowane warunki użytkowania (`Ustawienia → Wsparcie / System → Warunki i postanowienia / Usługi inteligentne`). Jeśli opcja ta pozostanie wyłączona, system VIDAA OS zablokuje wyświetlenie 4-cyfrowego kodu PIN podczas parowania.  
> *(Wskazówka dotycząca prywatności: po zakończeniu parowania można całkowicie bezpiecznie zablokować dostęp telewizora do Internetu/WAN na routerze; sterowanie lokalne w Home Assistant działa w 100% offline).*

> [!TIP]
> **Test diagnostyczny — sprawdzenie za pomocą oficjalnej aplikacji mobilnej**:  
> Jeśli 4-cyfrowy kod PIN nie pojawia się na ekranie lub parowanie kończy się niepowodzeniem, sprawdź połączenie za pomocą oficjalnej aplikacji **VIDAA** ([Apple App Store dla iOS](https://apps.apple.com/us/app/vidaa/id1526408639) lub [Google Play Store dla Androida](https://play.google.com/store/apps/details?id=com.universal.remote.multi)). Jeśli oficjalna aplikacja również nie może się połączyć, sprawdź akceptację usług inteligentnych w menu telewizora. *Pamiętaj o całkowitym wymuszeniu zamknięcia aplikacji mobilnej przed parowaniem w Home Assistant, aby uniknąć konfliktów sesji!*

---

## 📺 Obsługiwane marki i modele telewizorów

Oficjalne wsparcie dla **wszystkich telewizorów i projektorów z systemem VIDAA OS** (parowanie za pomocą **4-cyfrowego kodu PIN**):

- 📺 **Hisense** (serie U6, U7, U8, UX, A6, A7 — wersje U4 do U8, roczniki 2018–2026+)
- 📺 **Toshiba** (modele C350, M550, Z670 z systemem VIDAA)
- 📺 **Loewe** (serie We. SEE, stellar z systemem VIDAA OS)
- 📺 **Philips / TPV** (serie OLED, The One, PUS wyposażone w VIDAA OS)
- 📺 **Sharp, JVC, Schneider, Beko, Telefunken** oraz inni licencjonowani partnerzy
- 📽️ **TOPTRO** (przenośne projektory smart z systemem VIDAA OS)

---

## ✨ Główne funkcje

- **100% lokalna kontrola w sieci LAN (`iot_class: local_push`)**: Brak jakichkolwiek zależności od chmury, zerowa zależność od zewnętrznych serwerów, pełna obsługa odizolowanych sieci VLAN IoT (zablokowany ruch WAN).
- **Wygodny uploader certyfikatów w przeglądarce**: Przesyłaj oficjalne pakiety aplikacji (`.apk`/`.xapk`), archiwa PKCS#12 (`.p12`/`.pfx`) lub pliki `.pem` bezpośrednio przez interfejs Home Assistant z automatycznym rozpakowywaniem w pamięci RAM, deszyfrowaniem i wykrywaniem marki bez potrzeby używania terminala czy udziałów sieciowych Samba.
- **Odtwarzacz multimedialny (`media_player`)**: Włączanie/wyłączanie, płynna regulacja głośności, przełączanie wejść HDMI, przełączanie kanałów TV, szybkie uruchamianie aplikacji oraz kontekstowe przyciski nawigacji.
- **Dedykowany wirtualny pilot (`remote`)**: Klawisze nawigacyjne D-pad, klawiatura numeryczna, przyciski funkcyjne, przyciski kolorowe oraz w pełni konfigurowalne opóźnienia i powtórzenia klawiszy.
- **Regulacja parametrów obrazu i dźwięku (`select` i `number`)**: Zmiana trybów obrazu (`Standardowy`, `Kino`, `Dynamiczny`, `Sport`, `Filmmaker`) oraz precyzyjne suwaki podświetlenia, jasności i kontrastu; zmiana profili dźwięku korektora i wyjścia audio.
- **Automatyzacje włączania (`device_trigger`)**: Natywna obsługa wyzwalacza `vidaa.turn_on` do wygodnego sterowania inteligentnymi gniazdkami lub wysyłania pakietów Wake-on-LAN.

---

## 📚 Biblioteka dokumentacji

| Poradnik | Opis |
| :--- | :--- |
| 🔰 **[Szybki start dla początkujących](../quick_start_beginners.md)** | Błyskawiczna 2-minutowa konfiguracja za pomocą przeciągania plików w przeglądarce. |
| ⚙️ **[Konfiguracja i parametry opcji](../parameters.md)** | Pełne zestawienie parametrów konfiguracyjnych i zakładek menu. |
| ⚡ **[Zasilanie i tryby czuwania](../power_and_standby_settings.md)** | Architektura czuwania, szybki start i zapobieganie unieważnianiu tokenów. |
| 📱 **[Karty i panele Lovelace](../lovelace_cards.md)** | Szablony kart wirtualnego pilota, Button Card i gotowe pulpity. |
| 🛠️ **[Usługi i przykłady automatyzacji](../services_and_automations.md)** | Gotowe przepisy YAML na tryby kinowe, sekwencje klawiszy i wprowadzanie tekstu. |
| 🔒 **[Zaawansowana konfiguracja SSL](../certificates.md)** | Własne certyfikaty PEM, polecenia OpenSSL i weryfikacja kluczy. |
| 🧪 **[Narzędzia diagnostyczne i testowe CLI](../cli_tools.md)** | Samodzielne skrypty diagnostyczne (`scripts/test_client.py`, `scripts/diag.sh`). |
| 🩺 **[Rozwiązywanie problemów](../troubleshooting.md)** | Diagnoza błędów połączenia, problemów z certyfikatami i procedury naprawcze. |
