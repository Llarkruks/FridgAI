import json
import time
from pathlib import Path

import cv2
import joblib
import numpy as np
from skimage.feature import hog
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CROPS_DIR = PROJECT_ROOT / "data" / "processed" / "crops"
ZOO_DIR = PROJECT_ROOT / "artifacts" / "model_zoo"
ZOO_DIR.mkdir(parents=True, exist_ok=True)

TOP12_CLASSES = [
    "butter", "carrot", "cheese", "chicken", "eggs", "fish",
    "garlic", "lemon", "milk", "onion", "potato", "tomato",
]
MAX_PER_CLASS = 350

FEATURE_LABELS = {
    "raw_rgb": "Raw RGB (32×32)",
    "gray_blur": "Grayscale + Blur (64×64)",
    "hog": "HOG (Forma y bordes)",
    "hog_hsv": "HOG + Color HSV",
}


def extract_feature(bgr: np.ndarray, feat_key: str) -> np.ndarray:
    if feat_key == "raw_rgb":
        resized = cv2.resize(bgr, (32, 32), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return (rgb.astype(np.float32) / 255.0).flatten()

    resized = cv2.resize(bgr, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    if feat_key == "gray_blur":
        return (blur.astype(np.float32) / 255.0).flatten()

    hog_feat = hog(
        blur,
        orientations=9,
        pixels_per_cell=(8, 8),
        cells_per_block=(2, 2),
        block_norm="L2-Hys",
        feature_vector=True,
    ).astype(np.float32)

    if feat_key == "hog":
        return hog_feat

    if feat_key == "hog_hsv":
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 3], [0, 180, 0, 256, 0, 256])
        hsv_feat = cv2.normalize(hist, hist).flatten().astype(np.float32)
        return np.hstack([hog_feat, hsv_feat])

    raise ValueError(f"Extractor desconocido: {feat_key}")


def build_models():
    return {
        "knn": ("kNN (k=5)", KNeighborsClassifier(n_neighbors=5, n_jobs=-1)),
        "dt": ("Decision Tree", DecisionTreeClassifier(max_depth=15, random_state=42)),
        "gnb": ("Gaussian Naive Bayes", GaussianNB()),
        "mlp": ("Neural Net (MLP)", MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=35, random_state=42)),
        "svm": ("RBF SVM", SVC(kernel="rbf", C=1.0, decision_function_shape="ovr", random_state=42)),
        "rf": ("Random Forest", RandomForestClassifier(n_estimators=150, random_state=42, n_jobs=-1)),
        "hgb": (
            "HistGradientBoosting",
            HistGradientBoostingClassifier(max_iter=80, early_stopping=True, random_state=42),
        ),
    }


def load_crops():
    if not CROPS_DIR.exists():
        raise FileNotFoundError(
            f"No existe '{CROPS_DIR}'. Ejecuta primero ml/01_prep_vision_dataset.py."
        )

    images, labels = [], []
    class_dirs = sorted([d for d in CROPS_DIR.iterdir() if d.is_dir()])
    available = {d.name.lower(): d for d in class_dirs}

    target_classes = [c for c in TOP12_CLASSES if c in available]
    if not target_classes:
        target_classes = sorted(available.keys())[:12]

    for cls_name in target_classes:
        img_paths = sorted(
            [p for p in available[cls_name].iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        )[:MAX_PER_CLASS]
        for p in img_paths:
            img = cv2.imread(str(p))
            if img is not None:
                images.append(img)
                labels.append(cls_name)

    print(f"Cargadas {len(images)} imágenes de {len(target_classes)} clases: {target_classes}")
    return images, labels, target_classes


def main():
    images, raw_labels, classes = load_crops()
    le = LabelEncoder()
    y = le.fit_transform(raw_labels)

    idx_all = np.arange(len(images))
    idx_train, idx_test = train_test_split(idx_all, test_size=0.20, stratify=y, random_state=42)
    y_train, y_test = y[idx_train], y[idx_test]

    summary = {
        "classes": list(le.classes_),
        "n_train": int(len(idx_train)),
        "n_test": int(len(idx_test)),
        "features": FEATURE_LABELS,
        "models": {k: v[0] for k, v in build_models().items()},
        "results": [],
    }

    for feat_key, feat_label in FEATURE_LABELS.items():
        print(f"\n=== Extrayendo características: {feat_label} ===")
        t_ext = time.perf_counter()
        X_all = np.vstack([extract_feature(img, feat_key) for img in images])
        ext_ms_per_img = round(((time.perf_counter() - t_ext) / len(images)) * 1000, 3)
        X_train, X_test = X_all[idx_train], X_all[idx_test]
        print(f"Shape: {X_all.shape} | Extracción: {ext_ms_per_img} ms/img")

        for model_key, (model_label, clf) in build_models().items():
            pipe = Pipeline([("scaler", StandardScaler()), ("clf", clf)])
            t0 = time.perf_counter()
            pipe.fit(X_train, y_train)
            train_s = round(time.perf_counter() - t0, 3)

            t1 = time.perf_counter()
            y_pred = pipe.predict(X_test)
            pred_s = round(time.perf_counter() - t1, 4)
            pred_ms_per_img = round((pred_s / len(X_test)) * 1000, 3)

            acc = round(float(accuracy_score(y_test, y_pred)), 4)
            f1 = round(float(f1_score(y_test, y_pred, average="macro")), 4)
            cm = confusion_matrix(y_test, y_pred).tolist()

            out_path = ZOO_DIR / f"{feat_key}__{model_key}.joblib"
            joblib.dump(pipe, out_path, compress=3)

            summary["results"].append(
                {
                    "feature_key": feat_key,
                    "feature_label": feat_label,
                    "n_features": int(X_all.shape[1]),
                    "model_key": model_key,
                    "model_label": model_label,
                    "accuracy": acc,
                    "f1_macro": f1,
                    "train_s": train_s,
                    "pred_s": pred_s,
                    "extract_ms_img": ext_ms_per_img,
                    "pred_ms_img": pred_ms_per_img,
                    "confusion_matrix": cm,
                }
            )
            print(f"  [{model_label:20s}] Acc={acc:.4f} | F1={f1:.4f} | Train={train_s:6.2f}s | Pred={pred_ms_per_img:.3f} ms/img")

    with open(ZOO_DIR / "zoo_metrics.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nExportación completada: {len(summary['results'])} pipelines guardados en {ZOO_DIR}")


if __name__ == "__main__":
    main()