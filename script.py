import os

ruta = "C:\4rt\RAIA\Proyecto\food_image_dataset"

for root, dirs, files in os.walk(ruta):
    imgs = [f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    if imgs:
        carpeta = os.path.relpath(root, ruta)
        print(f"[{carpeta}] -> {len(imgs)} imgs | Ejemplos: {imgs[:3]}")