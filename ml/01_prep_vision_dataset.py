import os
import json
from pathlib import Path
from collections import Counter
import cv2
import yaml

# Raíz del proyecto: C:\4rt\RAIA\Proyecto (independiente de desde dónde ejecutes el script)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Busca automáticamente dónde está data.yaml dentro del proyecto
yaml_files = list(PROJECT_ROOT.rglob("data.yaml"))
if not yaml_files:
    raise FileNotFoundError(
        f"No se encontró ningún 'data.yaml' dentro de {PROJECT_ROOT}. "
        "Asegúrate de descomprimir el .zip de Roboflow dentro de la carpeta Proyecto."
    )

DATA_YAML_PATH = yaml_files[0]
DATASET_DIR = str(DATA_YAML_PATH.parent)
OUT_CROPS_DIR = str(PROJECT_ROOT / "data" / "processed" / "crops")
ARTIFACTS_DIR = str(PROJECT_ROOT / "artifacts")

os.makedirs(OUT_CROPS_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)
print("Dataset detectado en:", DATASET_DIR)

EXCLUDED_CLASSES = {"date", "lamb", "bulgur", "okra"}
MAX_CROPS_PER_CLASS = 350
MIN_BOX_PX = 24

with open(DATA_YAML_PATH, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
with open(os.path.join(DATASET_DIR, "data.yaml"), "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

class_names = cfg["names"]
raw_counts = Counter()
saved_counts = Counter()

for split in ["train", "valid", "test"]:
    img_dir = os.path.join(DATASET_DIR, split, "images")
    lbl_dir = os.path.join(DATASET_DIR, split, "labels")
    if not os.path.exists(lbl_dir):
        continue

    for lbl_file in os.listdir(lbl_dir):
        if not lbl_file.endswith(".txt"):
            continue
        base = os.path.splitext(lbl_file)[0]
        img_path = os.path.join(img_dir, base + ".jpg")
        if not os.path.exists(img_path):
            img_path = os.path.join(img_dir, base + ".png")
            if not os.path.exists(img_path):
                continue

        img = cv2.imread(img_path)
        if img is None:
            continue
        h, w = img.shape[:2]

        with open(os.path.join(lbl_dir, lbl_file), "r", encoding="utf-8") as lf:
            for idx, line in enumerate(lf):
                parts = line.strip().split()
                if len(parts) != 5:
                    continue
                cls_id = int(parts[0])
                cls_name = class_names[cls_id]
                raw_counts[cls_name] += 1

                if cls_name in EXCLUDED_CLASSES or saved_counts[cls_name] >= MAX_CROPS_PER_CLASS:
                    continue

                xc, yc, bw, bh = map(float, parts[1:])
                x1 = max(0, int((xc - bw / 2) * w))
                y1 = max(0, int((yc - bh / 2) * h))
                x2 = min(w, int((xc + bw / 2) * w))
                y2 = min(h, int((yc + bh / 2) * h))

                if (x2 - x1) < MIN_BOX_PX or (y2 - y1) < MIN_BOX_PX:
                    continue

                crop = img[y1:y2, x1:x2]
                cls_folder = os.path.join(OUT_CROPS_DIR, cls_name)
                os.makedirs(cls_folder, exist_ok=True)
                cv2.imwrite(os.path.join(cls_folder, f"{split}_{base}_{idx}.jpg"), crop)
                saved_counts[cls_name] += 1

eda_summary = {
    "total_annotations_raw": sum(raw_counts.values()),
    "raw_class_distribution": dict(raw_counts.most_common()),
    "excluded_classes": sorted(EXCLUDED_CLASSES),
    "crops_saved_per_class": dict(saved_counts.most_common()),
}
with open(os.path.join(ARTIFACTS_DIR, "vision_eda.json"), "w", encoding="utf-8") as f:
    json.dump(eda_summary, f, indent=2, ensure_ascii=False)

print("Total anotaciones originales:", eda_summary["total_annotations_raw"])
print("Recortes guardados por clase (top 10):", saved_counts.most_common(10))
print("Clases con menos muestras:", saved_counts.most_common()[-5:])