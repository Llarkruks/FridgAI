import io
import json
import pickle
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageOps
from scipy import sparse
from sklearn.metrics.pairwise import cosine_similarity
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


class TTLCache:
    def __init__(self, ttl_seconds: int = 60, maxsize: int = 256):
        self.ttl = ttl_seconds
        self.maxsize = maxsize
        self._store: Dict[tuple, Tuple[float, object]] = {}

    def get(self, key: tuple):
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: tuple, value: object) -> None:
        if len(self._store) >= self.maxsize:
            self._store.clear()
        self._store[key] = (time.time() + self.ttl, value)

    def clear(self) -> None:
        self._store.clear()


class MLEngine:
    def __init__(self):
        self.yolo_model: Optional[YOLO] = None
        self.recipes_df: Optional[pd.DataFrame] = None
        self.vectorizer = None
        self.tfidf_matrix = None
        self.yolo_to_es: Dict[str, str] = {}
        self.pantry_basics: List[str] = []

        # Listas pre-extraídas para inferencia <10 ms
        self._titles: List[str] = []
        self._categories: List[str] = []
        self._instructions: List[str] = []
        self._sources: List[Optional[str]] = []
        self._ing_sets: List[set] = []

        self.recommend_cache = TTLCache(ttl_seconds=60, maxsize=256)

    def load_all(self) -> None:
        # 1. Mapeos EN -> ES y básicos de despensa
        with open(ARTIFACTS_DIR / "mappings.json", "r", encoding="utf-8") as f:
            maps = json.load(f)
        self.yolo_to_es = maps["yolo_to_es"]
        self.pantry_basics = maps["pantry_basics"]

        # 2. Catálogo limpio de recetas + matriz TF-IDF
        self.recipes_df = pd.read_parquet(PROCESSED_DIR / "recipes_clean.parquet")
        with open(ARTIFACTS_DIR / "tfidf_vectorizer.pkl", "rb") as f:
            self.vectorizer = pickle.load(f)
        self.tfidf_matrix = sparse.load_npz(ARTIFACTS_DIR / "tfidf_matrix.npz")

        self._titles = self.recipes_df["Dish_Title"].astype(str).tolist()
        self._categories = self.recipes_df["Recipe_category"].astype(str).tolist()
        self._instructions = self.recipes_df["Recipe"].astype(str).tolist()
        self._sources = [
            str(s) if pd.notna(s) and str(s).startswith("http") else None
            for s in self.recipes_df["Source"].tolist()
        ]
        self._ing_sets = [set(lst) for lst in self.recipes_df["parsed_ingredients"].tolist()]

        # 3. Modelo YOLO11s en RAM
        best_pt = ARTIFACTS_DIR / "best.pt"
        if not best_pt.exists():
            raise FileNotFoundError(
                f"No se encontró '{best_pt}'. Copia tu best.pt descargado de Colab en artifacts/."
            )
        self.yolo_model = YOLO(str(best_pt))

    @staticmethod
    def _prepare_image(image_bytes: bytes, enhance: bool = False) -> Image.Image:
        # Corrige rotación EXIF (clave para cámara web y futuras capturas desde móvil/Unity)
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
        if not enhance:
            return img

        # Mejora de contraste local (CLAHE) solo sobre luminancia (canal L en LAB)
        # para recuperar detalle en webcams oscuras sin distorsionar colores reales
        rgb = np.array(img)
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_enh = clahe.apply(l_chan)
        rgb_enh = cv2.cvtColor(cv2.merge([l_enh, a_chan, b_chan]), cv2.COLOR_LAB2RGB)
        return Image.fromarray(rgb_enh)

    def recognize_image(
        self,
        image_bytes: bytes,
        conf: float = 0.30,
        enhance: bool = False,
        tta: bool = False,
        imgsz: int = 640,
    ) -> Tuple[float, List[dict]]:
        t0 = time.perf_counter()
        img = self._prepare_image(image_bytes, enhance=enhance)
        results = self.yolo_model.predict(
            source=img,
            conf=conf,
            iou=0.45,
            imgsz=imgsz,
            augment=tta,
            verbose=False,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        detected: List[dict] = []
        if results and results[0].boxes is not None:
            names = results[0].names
            for box in results[0].boxes:
                cls_en = names[int(box.cls[0])]
                # Ignora clases fuera del catálogo culinario mapeado
                if cls_en not in self.yolo_to_es:
                    continue
                confidence = round(float(box.conf[0]), 4)
                bbox = [round(float(v), 2) for v in box.xyxy[0].tolist()]
                detected.append(
                    {
                        "class_en": cls_en,
                        "ingredient_es": self.yolo_to_es[cls_en],
                        "confidence": confidence,
                        "bbox": bbox,
                    }
                )

        detected.sort(key=lambda d: d["confidence"], reverse=True)
        return elapsed_ms, detected

    def recommend(
        self,
        ingredients: List[str],
        max_missing: int = 5,
        top_k: int = 5,
        category: Optional[str] = None,
    ) -> List[dict]:
        norm_ings = tuple(sorted({ing.strip().lower() for ing in ingredients if ing.strip()}))
        cache_key = (norm_ings, max_missing, top_k, category or "")
        cached = self.recommend_cache.get(cache_key)
        if cached is not None:
            return cached

        user_set = set(norm_ings)
        q_vec = self.vectorizer.transform([" ".join(user_set)])
        sims = cosine_similarity(q_vec, self.tfidf_matrix).flatten()

        pool = min(400, len(sims))
        top_idx = np.argpartition(sims, -pool)[-pool:]

        candidates = []
        for idx in top_idx:
            sim = float(sims[idx])
            if sim <= 0.0:
                continue
            if category and self._categories[idx] != category:
                continue
            rec_ings = self._ing_sets[idx]
            matched = rec_ings & user_set
            missing = rec_ings - user_set
            if len(missing) > max_missing:
                continue
            coverage = len(matched) / len(rec_ings)
            score = 0.6 * coverage + 0.4 * sim
            candidates.append(
                {
                    "recipe_id": int(idx),
                    "title": self._titles[idx],
                    "category": self._categories[idx],
                    "match_pct": round(coverage * 100.0, 1),
                    "cosine_sim": round(sim, 4),
                    "score": round(score, 4),
                    "matched_ingredients": sorted(matched),
                    "missing_ingredients": sorted(missing),
                    "instructions": self._instructions[idx],
                    "source_url": self._sources[idx],
                }
            )

        candidates.sort(key=lambda x: (x["score"], -len(x["missing_ingredients"])), reverse=True)
        output = candidates[:top_k]
        self.recommend_cache.set(cache_key, output)
        return output

    def get_recipe_detail(self, recipe_id: int) -> Optional[dict]:
        if recipe_id < 0 or recipe_id >= len(self.recipes_df):
            return None
        row = self.recipes_df.iloc[recipe_id]
        src = str(row["Source"]) if pd.notna(row["Source"]) and str(row["Source"]).startswith("http") else None
        return {
            "recipe_id": int(row["recipe_id"]),
            "title": str(row["Dish_Title"]),
            "category": str(row["Recipe_category"]),
            "subcategory": str(row["Recipe_subcategory"]) if pd.notna(row["Recipe_subcategory"]) else None,
            "raw_ingredients": str(row["Recipe_ingredients"]),
            "parsed_ingredients": list(row["parsed_ingredients"]),
            "parsed_pantry": list(row["parsed_pantry"]),
            "instructions": str(row["Recipe"]),
            "source_url": src,
        }

    def get_categories(self) -> List[str]:
        return sorted(set(self._categories))

    def get_ml_metrics(self) -> dict:
        out = {}
        for fname, key in [
            ("vision_eda.json", "vision_eda"),
            ("classic_ml_metrics.json", "classic_ml"),
            ("yolo_metrics.json", "yolo"),
            ("recommender_metrics.json", "recommender"),
        ]:
            path = ARTIFACTS_DIR / fname
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    out[key] = json.load(f)
        return out


ml_engine = MLEngine()