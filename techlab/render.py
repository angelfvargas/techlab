"""Dibujo del resultado sobre la foto, sin etiquetas para que se lea la góndola."""
from PIL import Image, ImageDraw

VERDE = (34, 197, 94)
AZUL = (37, 99, 235)
ROJO = (239, 68, 68)


def pintar(ruta: str, dets, destino: str) -> str:
    img = Image.open(ruta).convert("RGB")
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    grosor = max(2, int(min(img.size) / 500))
    for det in dets:
        if det.tipo == "vacio":
            d.rectangle([det.x1, det.y1, det.x2, det.y2],
                        fill=ROJO + (80,), outline=ROJO + (255,), width=grosor + 1)
        else:
            c = AZUL if det.marca else VERDE
            d.rectangle([det.x1, det.y1, det.x2, det.y2], outline=c + (255,), width=grosor)
    img = Image.alpha_composite(img.convert("RGBA"), capa).convert("RGB")
    img.save(destino, quality=88)
    return destino
