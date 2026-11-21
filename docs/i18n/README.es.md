# Integración VIDAA Smart TV para Home Assistant

<p align="center">
  <a href="../../README.md"><img src="https://img.shields.io/badge/🇬🇧_English-gray?style=flat-square" alt="English"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/🇩🇪_Deutsch-gray?style=flat-square" alt="Deutsch"></a>
  <a href="README.it.md"><img src="https://img.shields.io/badge/🇮🇹_Italiano-gray?style=flat-square" alt="Italiano"></a>
  <a href="README.fr.md"><img src="https://img.shields.io/badge/🇫🇷_Français-gray?style=flat-square" alt="Français"></a>
  <a href="README.ru.md"><img src="https://img.shields.io/badge/🇷🇺_Русский-gray?style=flat-square" alt="Русский"></a>
  <a href="README.uk.md"><img src="https://img.shields.io/badge/🇺🇦_Українська-gray?style=flat-square" alt="Українська"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/🇨🇳_简体中文-gray?style=flat-square" alt="简体中文"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/🇪🇸_Español-blue?style=flat-square" alt="Español"></a>
  <a href="README.pl.md"><img src="https://img.shields.io/badge/🇵🇱_Polski-gray?style=flat-square" alt="Polski"></a>
</p>

[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/default)
[![Documentation](https://img.shields.io/badge/docs-stevene.enuff.com-blue.svg)](https://stevene.enuff.com/vidaa)
[![GitHub Release](https://img.shields.io/github/v/release/stevene1919/hisense_vidaa)](https://github.com/stevene1919/hisense_vidaa/releases)

Una integración nativa de Home Assistant para televisores inteligentes y proyectores con **VIDAA OS** (Hisense, Toshiba, Loewe, Philips, Sharp, JVC, TOPTRO y marcas asociadas).

Se conecta **directamente** al broker MQTT interno del televisor (puerto TLS `36669`) mediante certificados de cliente, ofreciendo actualizaciones push locales instantáneas, control de reproducción multimedia, inicio de aplicaciones, Wake-on-LAN y navegación remota virtual sin necesidad de puentes externos ni servicios en la nube.

---

## 🔰 Inicio Rápido (Guía para Principiantes)

La configuración de su televisor toma menos de 2 minutos en 3 sencillos pasos:

### 1️⃣ Instalación a través de Marketplace (HACS)
Haga clic en el botón a continuación (o busque **VIDAA Smart TV** en Marketplace (HACS) → Integraciones → Descargar):

[![Abrir Marketplace (HACS)](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stevene1919&repository=hisense_vidaa&category=integration)

### 2️⃣ Certificados de Cliente (Carga en 1 Clic desde el Navegador o Colocación Manual)
Los televisores VIDAA requieren TLS mutuo en el puerto 36669.
- **✨ Carga en 1 Clic desde el Navegador (Recomendado):** Durante la configuración inicial, Home Assistant verifica automáticamente la presencia de certificados. Si no se encuentran, simplemente cargue el paquete de la aplicación oficial (`.apk` o `.xapk`), un almacén de claves PKCS#12 (`client_mobile_android.p12`, `El.p12`, `3R.p12`, `toshiba.p12`) o un archivo combinado `.pem` directamente desde su navegador. Home Assistant extraerá, descifrará y guardará los certificados de forma totalmente automática.
- **Colocación Manual y Rutas Personalizadas:** De forma alternativa, puede colocar los archivos `client_mobile_android.p12`, `El.p12`, `3R.p12` o `hisense.crt` + `hisense.key` en el directorio `/config/ssl/` (detección automática), o seleccionar la opción para ingresar rutas personalizadas en el cuadro de configuración.

> [!TIP]
> **¿Necesita una guía paso a paso con capturas de pantalla?**  
> Consulte la **[Guía de Inicio Rápido para Principiantes](../quick_start_beginners.md)** (para comandos avanzados de OpenSSL y claves PEM personalizadas, consulte la [Guía Avanzada SSL](../certificates.md)).

### 3️⃣ Emparejar con el PIN en Pantalla
1. Reinicie Home Assistant (`Ajustes` → `Sistema` → `Reiniciar`).
2. Vaya a **Ajustes → Dispositivos y Servicios → Añadir Integración** y busque **VIDAA Smart TV**.
3. Ingrese la dirección IP local de su televisor y haga clic en **Enviar**.
4. ¡Escriba el **código PIN de 4 dígitos** que aparece en la pantalla del televisor para completar la configuración!

> [!IMPORTANT]
> **Requisito del televisor: activar servicios inteligentes / conectados**:  
> El televisor debe tener los **Servicios Conectados / Inteligentes** activados y los términos de uso aceptados (`Ajustes → Soporte / Sistema → Términos y Condiciones / Servicios Inteligentes`). Si esta opción permanece desactivada, VIDAA OS bloqueará el cuadro de diálogo del PIN de 4 dígitos durante el emparejamiento.  
> *(Consejo de privacidad: una vez completado el emparejamiento, es totalmente seguro bloquear el acceso a Internet/WAN del televisor en su router; el control local en Home Assistant funciona 100% sin conexión).*

> [!TIP]
> **Prueba de diagnóstico: verificación con la aplicación móvil oficial**:  
> Si el PIN de 4 dígitos no aparece o el emparejamiento falla, pruebe la conexión utilizando la aplicación oficial **VIDAA** ([Apple App Store para iOS](https://apps.apple.com/us/app/vidaa/id1526408639) o [Google Play Store para Android](https://play.google.com/store/apps/details?id=com.universal.remote.multi)). Si la aplicación oficial tampoco se conecta, compruebe la aceptación de los servicios inteligentes en el televisor. *¡Recuerde forzar el cierre completo de la aplicación móvil antes de emparejar en Home Assistant para evitar conflictos de sesión!*

---

## 📺 Marcas y Modelos de Televisores Compatibles

Soporte oficial para **cualquier televisor inteligente o proyector con VIDAA OS** (emparejamiento mediante **PIN de 4 dígitos en pantalla**):

- 📺 **Hisense** (series U6, U7, U8, UX, A6, A7 — versiones U4 a U8, modelos de 2018 a 2026+)
- 📺 **Toshiba** (ediciones C350, M550, Z670 con VIDAA)
- 📺 **Loewe** (series We. SEE, stellar con VIDAA OS)
- 📺 **Philips / TPV** (series OLED, The One, PUS con VIDAA OS)
- 📺 **Sharp, JVC, Schneider, Beko, Telefunken** y otras marcas asociadas con licencia
- 📽️ **TOPTRO** (proyectores inteligentes portátiles con VIDAA OS)

---

## ✨ Características Principales

- **Control 100% Local en Red LAN (`iot_class: local_push`)**: Sin dependencias de la nube, sin llamadas a servidores externos y compatibilidad total con VLANs IoT aisladas (tráfico WAN bloqueado).
- **Cargador Cómodo de Certificados desde el Navegador**: Cargue paquetes oficiales (`.apk`/`.xapk`), almacenes de claves PKCS#12 (`.p12`/`.pfx`) o paquetes `.pem` directamente desde la interfaz web de Home Assistant con extracción en memoria, descifrado automático de contraseñas y detección de fabricante sin comandos de consola ni Samba.
- **Plataforma de Reproductor Multimedia (`media_player`)**: Encendido/apagado, ajuste de volumen, cambio de fuentes de entrada, sintonización de canales de TV, inicio rápido de aplicaciones y botones contextuales de reproducción.
- **Control Remoto Virtual Dedicado (`remote`)**: Navegación con cruceta D-pad, teclado numérico, botones de menú/inicio, botones de colores y repetición de pulsaciones totalmente configurable.
- **Ajustes de Imagen y Sonido (`select` y `number`)**: Modos de imagen (`Estándar`, `Cine`, `Dinámico`, `Deportes`, `Filmmaker`), controles deslizantes de brillo, contraste y luz de fondo; perfiles de ecualización y selección de salida de audio.
- **Automatizaciones de Encendido (`device_trigger`)**: Soporte nativo para el disparador `vidaa.turn_on` para activar enchufes inteligentes o emitir paquetes Wake-on-LAN.

---

## 📚 Biblioteca de Documentación

| Guía | Descripción |
| :--- | :--- |
| 🔰 **[Guía de Inicio para Principiantes](../quick_start_beginners.md)** | Configuración en 2 minutos arrastrando archivos desde el navegador. |
| ⚙️ **[Parámetros y Opciones](../parameters.md)** | Referencia completa de todos los campos de configuración y menús de opciones. |
| ⚡ **[Ajustes de Energía y Modo de Espera](../power_and_standby_settings.md)** | Comportamiento del modo de espera, inicio rápido y prevención de pérdida de tokens. |
| 📱 **[Tarjetas y Paneles Lovelace](../lovelace_cards.md)** | Mandos a distancia virtuales, Button Cards y plantillas de interfaz de usuario. |
| 🛠️ **[Servicios y Automatizaciones](../services_and_automations.md)** | Recetas YAML para modos de cine, secuencias de teclas e inserción de texto. |
| 🔒 **[Configuración Avanzada de SSL](../certificates.md)** | Certificados PEM personalizados, comandos OpenSSL y validación de claves. |
| 🧪 **[Herramientas de Diagnóstico y Pruebas CLI](../cli_tools.md)** | Utilidades autónomas de línea de comandos (`scripts/test_client.py`, `scripts/diag.sh`). |
| 🩺 **[Solución de Problemas](../troubleshooting.md)** | Diagnóstico de errores de emparejamiento, fallos de red y soluciones paso a paso. |
