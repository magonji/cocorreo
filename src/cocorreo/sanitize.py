"""Sanitización de HTML para mostrar cuerpos de correo con seguridad.

Quitamos `<script>`, `<iframe>`, event handlers, URLs `javascript:` y todo lo
que pueda ejecutar código en el navegador. El frontend además renderizará el
HTML resultante dentro de un `<iframe sandbox>` como defensa en profundidad.
"""

from __future__ import annotations

import bleach

ALLOWED_TAGS = [
    "a", "abbr", "address", "article", "aside", "b", "blockquote", "br",
    "caption", "cite", "code", "col", "colgroup", "dd", "del", "details",
    "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "img",
    "ins", "kbd", "li", "main", "mark", "nav", "ol", "p", "pre", "q",
    "s", "samp", "section", "small", "span", "strong", "sub", "summary",
    "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr",
    "u", "ul", "var", "wbr",
]

ALLOWED_ATTRIBUTES = {
    "*": ["class", "id", "title", "lang", "dir"],
    "a": ["href", "rel", "target", "name"],
    "img": ["src", "alt", "width", "height"],
    "table": ["border", "cellpadding", "cellspacing", "summary"],
    "td": ["colspan", "rowspan", "align", "valign"],
    "th": ["colspan", "rowspan", "align", "valign", "scope"],
    "col": ["span", "width"],
    "colgroup": ["span"],
    "time": ["datetime"],
    "ol": ["start", "type"],
    "ul": ["type"],
    "li": ["value"],
}

# `cid:` permite que el frontend resuelva referencias a imágenes inline.
ALLOWED_PROTOCOLS = ["http", "https", "mailto", "cid"]


def sanitize_html(html: str) -> str:
    if not html:
        return ""
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
