import os
import time
import json
import pickle
from pathlib import Path
import cv2
import numpy as np
from skimage.feature import hog
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CROPS_DIR = PROJECT_ROOT / "data" / "processed" / "crops"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

SELECTED_CLASSES = [
    "onion", "garlic", "eggs", "milk", "tomato", "butter",
    "cheese", "lemon", "chicken", "potato", "carrot", "fish"
]

def extract_hsv_hist(img_bgr, bins=(8, 4, 3)):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, bins, [0, 180, 0, 256, 0, 256])
    cv2.normalize(hist, hist)
    return hist.flatten()

X_raw, X_gray, X_hog, X_hog_hsv, y_labels = [], [], [], [], []

print("Cargando imágenes y extrayendo features (Raw RGB, Gray+Blur, HOG y HOG+HSV)...")
for cls in SELECTED_CLASSES:
    folder = CROPS_DIR / cls
    if not folder.exists():
        print(f"AVISO: No se encontró la carpeta {folder}")
        continue
    for fname in os.listdir(folder):
        img = cv2.imread(str(folder / fname))
        if img is None:
            continue

        img64 = cv2.resize(img, (64, 64))

        # 1) Raw RGB (32x32x3 = 3072)
        X_raw.append(cv2.resize(img, (32, 32)).flatten() / 255.0)

        # 2) Grayscale + Gaussian Blur (64x64 = 4096)
        gray = cv2.cvtColor(img64, cv2.COLOR_BGR2GRAY)
        gray_blur = cv2.GaussianBlur(gray, (3, 3), 0) / 255.0
        X_gray.append(gray_blur.flatten())

        # 3) HOG (forma y contornos = 1764)
        hog_feat = hog(
            gray_blur,
            orientations=9,
            pixels_per_cell=(8, 8),
            cells_per_block=(2, 2),
            block_norm="L2-Hys",
        )
        X_hog.append(hog_feat)

        # 4) Fusión HOG + Histograma de color HSV (1764 + 96 = 1860)
        hsv_feat = extract_hsv_hist(img64)
        X_hog_hsv.append(np.concatenate([hog_feat, hsv_feat]))

        y_labels.append(cls)

X_raw = np.array(X_raw, dtype=np.float32)
X_gray = np.array(X_gray, dtype=np.float32)
X_hog = np.array(X_hog, dtype=np.float32)
X_hog_hsv = np.array(X_hog_hsv, dtype=np.float32)
le = LabelEncoder()
y = le.fit_transform(y_labels)

print(f"Muestras: {len(y)} | Clases: {len(le.classes_)}")
print(f"Dims -> Raw: {X_raw.shape[1]} | Gray: {X_gray.shape[1]} | HOG: {X_hog.shape[1]} | HOG+HSV: {X_hog_hsv.shape[1]}\n")

# 1. Ablación de 4 niveles de representación visual (SVM RBF, Holdout 80/20 estratificado)
print("--- 1. ABLACIÓN DE CARACTERÍSTICAS (SVM RBF) ---")
ablation_results = {}
for feat_name, X_mat in [
    ("Raw RGB (3072)", X_raw),
    ("Gray+Blur (4096)", X_gray),
    ("HOG (1764)", X_hog),
    ("HOG + HSV Color (1860)", X_hog_hsv),
]:
    X_tr, X_te, y_tr, y_te = train_test_split(X_mat, y, test_size=0.2, stratify=y, random_state=42)
    pipe = Pipeline([("scaler", StandardScaler()), ("clf", SVC(kernel="rbf", random_state=42))])
    t0 = time.perf_counter()
    pipe.fit(X_tr, y_tr)
    t1 = time.perf_counter()
    preds = pipe.predict(X_te)
    t2 = time.perf_counter()
    ablation_results[feat_name] = {
        "n_features": int(X_mat.shape[1]),
        "accuracy": round(float(accuracy_score(y_te, preds)), 4),
        "f1_macro": round(float(f1_score(y_te, preds, average="macro")), 4),
        "train_s": round(t1 - t0, 3),
        "pred_s": round(t2 - t1, 3),
    }
    r = ablation_results[feat_name]
    print(f"  {feat_name:24s} | Acc: {r['accuracy']:.4f} | F1: {r['f1_macro']:.4f} | Train: {r['train_s']}s | Pred: {r['pred_s']}s")

# 2. Comparativa de 7 familias de clasificadores sobre HOG+HSV (5-Fold Stratified CV)
print("\n--- 2. COMPARATIVA DE 7 MODELOS SOBRE HOG+HSV (5-FOLD STRATIFIED CV) ---")
models = {
    "kNN (k=5)": KNeighborsClassifier(n_neighbors=5, n_jobs=-1),
    "Decision Tree": DecisionTreeClassifier(max_depth=15, random_state=42),
    "Gaussian Naive Bayes": GaussianNB(),
    "RBF SVM": SVC(kernel="rbf", random_state=42),
    "Neural Net (MLP)": MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=200, random_state=42),
    "Random Forest (Bagging)": RandomForestClassifier(n_estimators=150, random_state=42, n_jobs=-1),
    "HistGradientBoosting": HistGradientBoostingClassifier(max_iter=80, max_depth=6, random_state=42),
}

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
comparison = []

for name, clf in models.items():
    accs, precs, recs, f1s, tr_times, pr_times = [], [], [], [], [], []
    for train_idx, val_idx in skf.split(X_hog_hsv, y):
        pipe = Pipeline([("scaler", StandardScaler()), ("clf", clf)])
        t0 = time.perf_counter()
        pipe.fit(X_hog_hsv[train_idx], y[train_idx])
        t1 = time.perf_counter()
        y_pred = pipe.predict(X_hog_hsv[val_idx])
        t2 = time.perf_counter()

        accs.append(accuracy_score(y[val_idx], y_pred))
        precs.append(precision_score(y[val_idx], y_pred, average="macro", zero_division=0))
        recs.append(recall_score(y[val_idx], y_pred, average="macro", zero_division=0))
        f1s.append(f1_score(y[val_idx], y_pred, average="macro", zero_division=0))
        tr_times.append(t1 - t0)
        pr_times.append(t2 - t1)

    row = {
        "model": name,
        "accuracy_mean": round(float(np.mean(accs)), 4),
        "accuracy_std": round(float(np.std(accs)), 4),
        "precision_macro": round(float(np.mean(precs)), 4),
        "recall_macro": round(float(np.mean(recs)), 4),
        "f1_macro": round(float(np.mean(f1s)), 4),
        "train_time_s": round(float(np.mean(tr_times)), 3),
        "pred_time_s": round(float(np.mean(pr_times)), 4),
    }
    comparison.append(row)
    print(f"  {name:24s} | Acc: {row['accuracy_mean']:.4f} (+/-{row['accuracy_std']:.4f}) | F1: {row['f1_macro']:.4f} | Train: {row['train_time_s']}s | Pred: {row['pred_time_s']}s")

# 3. Guardar el mejor modelo clásico y su Matriz de Confusión (Holdout 80/20)
best_name = max(comparison, key=lambda r: r["f1_macro"])["model"]
X_tr, X_te, y_tr, y_te = train_test_split(X_hog_hsv, y, test_size=0.2, stratify=y, random_state=42)
best_pipe = Pipeline([("scaler", StandardScaler()), ("clf", models[best_name])])
best_pipe.fit(X_tr, y_tr)
cm = confusion_matrix(y_te, best_pipe.predict(X_te))

with open(ARTIFACTS_DIR / "classic_best.pkl", "wb") as f:
    pickle.dump({"pipeline": best_pipe, "label_encoder": le, "feature_mode": "hog_hsv"}, f)

with open(ARTIFACTS_DIR / "classic_ml_metrics.json", "w", encoding="utf-8") as f:
    json.dump({
        "classes": le.classes_.tolist(),
        "ablation": ablation_results,
        "cv_comparison": comparison,
        "best_model": best_name,
        "confusion_matrix": cm.tolist(),
    }, f, indent=2, ensure_ascii=False)

print(f"\nListo. Mejor modelo clásico: {best_name}")
print("Artefactos guardados en:", ARTIFACTS_DIR)