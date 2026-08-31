import re
import time
import hashlib
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

WEB_URL = "https://www.ebroauto.com/sala-de-prensa"
BASE_URL = "https://www.ebroauto.com"
ARCHIVO_RSS = "ebro.xml"
MAX_PAGINAS = 4
MAX_NOTICIAS = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

sesion = requests.Session()
sesion.headers.update(HEADERS)


def limpiar_texto(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def escapar_xml(texto):
    texto = str(texto or "")
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def descargar(url):
    ultimo_error = None

    for intento in range(3):
        try:
            respuesta = sesion.get(url, timeout=30)
            respuesta.raise_for_status()
            respuesta.encoding = respuesta.apparent_encoding or "utf-8"
            return respuesta.text
        except requests.RequestException as error:
            ultimo_error = error
            time.sleep(2 + intento * 2)

    raise RuntimeError(f"No se pudo descargar {url}: {ultimo_error}")


def obtener_enlaces():
    enlaces = []
    vistos = set()

    for pagina in range(1, MAX_PAGINAS + 1):
        url = WEB_URL if pagina == 1 else f"{WEB_URL}?page={pagina}"
        html = descargar(url)
        soup = BeautifulSoup(html, "html.parser")

        encontrados_pagina = 0

        for enlace in soup.find_all("a", href=True):
            href = enlace.get("href", "").strip()
            url_noticia = urljoin(BASE_URL, href)
            ruta = url_noticia.split("?", 1)[0].rstrip("/")

            if "/sala-de-prensa/" not in ruta:
                continue

            if ruta == WEB_URL.rstrip("/"):
                continue

            if ruta in vistos:
                continue

            texto = limpiar_texto(enlace.get_text(" ", strip=True))

            if not texto:
                continue

            vistos.add(ruta)
            enlaces.append(ruta)
            encontrados_pagina += 1

        if encontrados_pagina == 0:
            break

    return enlaces[:MAX_NOTICIAS]


def obtener_fecha(soup, texto_completo):
    # Formato mostrado en la ficha: 11.06.2026
    coincidencia = re.search(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b",
        texto_completo,
    )

    if coincidencia:
        dia, mes, anio = map(int, coincidencia.groups())
        return datetime(anio, mes, dia, 12, 0, tzinfo=timezone.utc)

    # Formato mostrado dentro de la noticia:
    # Jueves, 11 de junio 2026
    coincidencia = re.search(
        r"\b(\d{1,2})\s+de\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|octubre|noviembre|diciembre)"
        r"(?:\s+de)?\s+(20\d{2})\b",
        texto_completo.lower(),
    )

    if coincidencia:
        dia = int(coincidencia.group(1))
        mes = MESES[coincidencia.group(2)]
        anio = int(coincidencia.group(3))
        return datetime(anio, mes, dia, 12, 0, tzinfo=timezone.utc)

    time_elemento = soup.find("time")

    if time_elemento:
        fecha_iso = time_elemento.get("datetime", "").strip()

        if fecha_iso:
            try:
                fecha = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))

                if fecha.tzinfo is None:
                    fecha = fecha.replace(tzinfo=timezone.utc)

                return fecha.astimezone(timezone.utc)
            except ValueError:
                pass

    return None


def obtener_descripcion(soup, titulo):
    selectores = [
        "main article",
        "article",
        "main",
    ]

    contenedor = None

    for selector in selectores:
        candidato = soup.select_one(selector)

        if candidato:
            contenedor = candidato
            break

    if contenedor is None:
        contenedor = soup

    parrafos = []

    for parrafo in contenedor.find_all("p"):
        texto = limpiar_texto(parrafo.get_text(" ", strip=True))

        if not texto:
            continue

        if texto == titulo:
            continue

        if len(texto) < 35:
            continue

        texto_minusculas = texto.lower()

        if "política de privacidad" in texto_minusculas:
            continue

        if "suscríbete" in texto_minusculas:
            continue

        if "mantente al día" in texto_minusculas:
            continue

        parrafos.append(texto)

        if len(" ".join(parrafos)) >= 1500:
            break

    descripcion = " ".join(parrafos)

    if len(descripcion) > 1800:
        descripcion = descripcion[:1797].rsplit(" ", 1)[0] + "..."

    return descripcion or titulo


def obtener_noticia(url):
    html = descargar(url)
    soup = BeautifulSoup(html, "html.parser")

    titulo_elemento = soup.find("h1")

    if not titulo_elemento:
        return None

    titulo = limpiar_texto(titulo_elemento.get_text(" ", strip=True))

    if not titulo:
        return None

    texto_completo = limpiar_texto(soup.get_text(" ", strip=True))
    fecha = obtener_fecha(soup, texto_completo)
    descripcion = obtener_descripcion(soup, titulo)

    return {
        "titulo": titulo,
        "url": url,
        "fecha": fecha,
        "descripcion": descripcion,
    }


def obtener_noticias():
    noticias = []

    for url in obtener_enlaces():
        try:
            noticia = obtener_noticia(url)

            if noticia:
                noticias.append(noticia)
        except Exception as error:
            print(f"Aviso: no se pudo procesar {url}: {error}")

        time.sleep(0.25)

    if not noticias:
        raise RuntimeError("No se encontraron noticias de EBRO")

    noticias.sort(
        key=lambda noticia: noticia["fecha"]
        or datetime(1970, 1, 1, tzinfo=timezone.utc),
        reverse=True,
    )

    return noticias


def crear_rss(noticias):
    ahora = datetime.now(timezone.utc)

    elementos = []

    for noticia in noticias:
        fecha = noticia["fecha"] or ahora
        identificador = hashlib.sha256(
            noticia["url"].encode("utf-8")
        ).hexdigest()

        elementos.append(
            f"""    <item>
      <title>{escapar_xml(noticia["titulo"])}</title>
      <link>{escapar_xml(noticia["url"])}</link>
      <guid isPermaLink="false">{identificador}</guid>
      <pubDate>{format_datetime(fecha)}</pubDate>
      <description>{escapar_xml(noticia["descripcion"])}</description>
    </item>"""
        )

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>EBRO - Sala de prensa</title>
    <link>{escapar_xml(WEB_URL)}</link>
    <description>Últimas noticias y notas de prensa publicadas por EBRO</description>
    <language>es-es</language>
    <lastBuildDate>{format_datetime(ahora)}</lastBuildDate>
{chr(10).join(elementos)}
  </channel>
</rss>
"""

    with open(ARCHIVO_RSS, "w", encoding="utf-8", newline="\n") as archivo:
        archivo.write(rss)

    print(f"RSS creada correctamente: {ARCHIVO_RSS}")
    print(f"Noticias incluidas: {len(noticias)}")


def main():
    noticias = obtener_noticias()
    crear_rss(noticias)


if __name__ == "__main__":
    main()
