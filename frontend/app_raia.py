import json
import pickle
import time
from pathlib import Path

import cv2
import joblib
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image
from scipy import sparse
from skimage.feature import hog
from sklearn.metrics.pairwise import cosine_similarity

st.set_page_config(
    page_title="FridgIA — Smart Fridge RAIA",
    page_icon="🧊",
    layout="wide",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ZOO_DIR = ARTIFACTS_DIR / "model_zoo"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


# -------------------- CARGA DE RECURSOS EN RAM --------------------
@st.cache_resource
def load_core_resources():
    zoo_metrics_path = ZOO_DIR / "zoo_metrics.json"
    if not zoo_metrics_path.exists():
        return None

    with open(zoo_metrics_path, "r", encoding="utf-8") as f:
        zoo_metrics = json.load(f)

    with open(ARTIFACTS_DIR / "mappings.json", "r", encoding="utf-8") as f:
        maps = json.load(f)

    rec_metrics = {}
    rm_path = ARTIFACTS_DIR / "recommender_metrics.json"
    if rm_path.exists():
        with open(rm_path, "r", encoding="utf-8") as f:
            rec_metrics = json.load(f)

    recipes_df = pd.read_parquet(PROCESSED_DIR / "recipes_clean.parquet")
    with open(ARTIFACTS_DIR / "tfidf_vectorizer.pkl", "rb") as f:
        vectorizer = pickle.load(f)
    tfidf_matrix = sparse.load_npz(ARTIFACTS_DIR / "tfidf_matrix.npz")

    # Índice rápido de métricas por (feature_key, model_key)
    metrics_lookup = {
        (r["feature_key"], r["model_key"]): r for r in zoo_metrics["results"]
    }

    return {
        "zoo_metrics": zoo_metrics,
        "metrics_lookup": metrics_lookup,
        "classes": zoo_metrics["classes"],
        "features": zoo_metrics["features"],
        "models": zoo_metrics["models"],
        "en_to_es": maps.get("yolo_to_es", {}),
        "pantry_basics": maps.get("pantry_basics", []),
        "rec_metrics": rec_metrics,
        "recipes_df": recipes_df,
        "vectorizer": vectorizer,
        "tfidf_matrix": tfidf_matrix,
        "titles": recipes_df["Dish_Title"].astype(str).tolist(),
        "categories": recipes_df["Recipe_category"].astype(str).tolist(),
        "instructions": recipes_df["Recipe"].astype(str).tolist(),
        "sources": [
            str(s) if pd.notna(s) and str(s).startswith("http") else None
            for s in recipes_df["Source"].tolist()
        ],
        "ing_sets": [set(lst) for lst in recipes_df["parsed_ingredients"].tolist()],
    }


@st.cache_resource
def load_pipeline(feat_key: str, model_key: str):
    return joblib.load(ZOO_DIR / f"{feat_key}__{model_key}.joblib")


# -------------------- EXTRACCIÓN DE FEATURES E INFERENCIA --------------------
def extract_feature_and_visual(pil_img: Image.Image, feat_key: str):
    rgb = np.array(pil_img.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    if feat_key == "raw_rgb":
        resized_bgr = cv2.resize(bgr, (32, 32), interpolation=cv2.INTER_AREA)
        resized_rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
        vec = (resized_rgb.astype(np.float32) / 255.0).flatten()
        return vec.reshape(1, -1), {"rgb_32": resized_rgb}

    resized_bgr = cv2.resize(bgr, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)

    if feat_key == "gray_blur":
        vec = (blur.astype(np.float32) / 255.0).flatten()
        return vec.reshape(1, -1), {"gray_blur": blur}

    hog_feat, hog_vis = hog(
        blur,
        orientations=9,
        pixels_per_cell=(8, 8),
        cells_per_block=(2, 2),
        block_norm="L2-Hys",
        visualize=True,
        feature_vector=True,
    )
    hog_feat = hog_feat.astype(np.float32)
    hog_img = cv2.normalize(hog_vis, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    if feat_key == "hog":
        return hog_feat.reshape(1, -1), {"gray_blur": blur, "hog_img": hog_img}

    hsv = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 3], [0, 180, 0, 256, 0, 256])
    hsv_feat = cv2.normalize(hist, hist).flatten().astype(np.float32)
    hue_hist = cv2.calcHist([hsv], [0], None, [16], [0, 180]).flatten()

    vec = np.hstack([hog_feat, hsv_feat]).reshape(1, -1)
    return vec, {"gray_blur": blur, "hog_img": hog_img, "hue_hist": hue_hist}


def compute_scores(pipe, X: np.ndarray) -> np.ndarray:
    if hasattr(pipe, "predict_proba"):
        return pipe.predict_proba(X)[0]
    if hasattr(pipe, "decision_function"):
        raw = np.asarray(pipe.decision_function(X), dtype=np.float64).flatten()
        shifted = raw - np.max(raw)
        exp_s = np.exp(shifted)
        return exp_s / np.sum(exp_s)
    # Fallback determinista
    n_cls = len(pipe.classes_)
    probs = np.zeros(n_cls)
    pred = int(pipe.predict(X)[0])
    probs[pred] = 1.0
    return probs


def run_inference(pil_img: Image.Image, feat_key: str, model_key: str, res: dict):
    t0 = time.perf_counter()
    X, visuals = extract_feature_and_visual(pil_img, feat_key)
    t_ext = (time.perf_counter() - t0) * 1000

    pipe = load_pipeline(feat_key, model_key)
    t1 = time.perf_counter()
    pred_idx = int(pipe.predict(X)[0])
    probs = compute_scores(pipe, X)
    t_pred = (time.perf_counter() - t1) * 1000

    classes = res["classes"]
    en_to_es = res["en_to_es"]
    pred_en = classes[pred_idx]
    pred_es = en_to_es.get(pred_en, pred_en)

    probs_df = (
        pd.DataFrame(
            {
                "clase_en": classes,
                "ingrediente_es": [en_to_es.get(c, c) for c in classes],
                "confianza": probs,
            }
        )
        .sort_values("confianza", ascending=False)
        .reset_index(drop=True)
    )

    return {
        "pred_en": pred_en,
        "pred_es": pred_es,
        "confidence": float(probs[pred_idx]),
        "probs_df": probs_df,
        "visuals": visuals,
        "extract_ms": round(t_ext, 2),
        "pred_ms": round(t_pred, 2),
        "total_ms": round(t_ext + t_pred, 2),
        "n_features": int(X.shape[1]),
    }


def recommend_recipes(ingredients: list, res: dict, max_missing: int = 3, top_k: int = 5, category: str | None = None):
    t0 = time.perf_counter()
    user_set = {ing.strip().lower() for ing in ingredients if ing.strip()}
    q_vec = res["vectorizer"].transform([" ".join(user_set)])
    sims = cosine_similarity(q_vec, res["tfidf_matrix"]).flatten()

    pool = min(400, len(sims))
    top_idx = np.argpartition(sims, -pool)[-pool:]

    candidates = []
    for idx in top_idx:
        sim = float(sims[idx])
        if sim <= 0.0:
            continue
        if category and res["categories"][idx] != category:
            continue
        rec_ings = res["ing_sets"][idx]
        matched = rec_ings & user_set
        missing = rec_ings - user_set
        if len(missing) > max_missing:
            continue
        coverage = len(matched) / len(rec_ings)
        score = 0.6 * coverage + 0.4 * sim
        candidates.append(
            {
                "recipe_id": int(idx),
                "title": res["titles"][idx],
                "category": res["categories"][idx],
                "match_pct": round(coverage * 100.0, 1),
                "cosine_sim": round(sim, 4),
                "score": round(score, 4),
                "matched": sorted(matched),
                "missing": sorted(missing),
                "instructions": res["instructions"][idx],
                "source_url": res["sources"][idx],
            }
        )

    candidates.sort(key=lambda x: (x["score"], -len(x["missing"])), reverse=True)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    return candidates[:top_k], latency_ms


# -------------------- INICIALIZACIÓN Y BARRA LATERAL --------------------
res = load_core_resources()
if res is None:
    st.error(
        "No se han encontrado los modelos entrenados en `artifacts/model_zoo/`. "
        "Ejecuta primero `python ml/export_model_zoo.py` desde la raíz del proyecto."
    )
    st.stop()

if "basket" not in st.session_state:
    st.session_state.basket = []

with st.sidebar:
    st.title("🧊 FridgIA")
    st.caption("Reconocimiento visual de ingredientes y recomendador inteligente de recetas.")
    st.divider()

    page = st.radio(
        "Navegación",
        [
            "📷 Escáner de Ingredientes",
            "⚔️ Comparador en Vivo",
            "🍳 Mi Nevera y Recetas",
            "📊 Evaluación y Métricas",
        ],
    )

    st.divider()
    st.subheader(f"🧺 Mi Nevera ({len(st.session_state.basket)})")
    if st.session_state.basket:
        st.write(", ".join(sorted(st.session_state.basket)))
        if st.button("Vaciar nevera", use_container_width=True):
            st.session_state.basket = []
            st.rerun()
    else:
        st.caption("Sin ingredientes todavía.")


# -------------------- VISTA 1: ESCÁNER CON SELECTOR DE FEATURE + MODELO --------------------
if page == "📷 Escáner de Ingredientes":
    st.header("📷 Escáner Inteligente de Ingredientes")

    feat_keys = list(res["features"].keys())
    model_keys = list(res["models"].keys())

    c_sel1, c_sel2, c_sel3 = st.columns([2, 2, 2])
    feat_key = c_sel1.selectbox(
        "1. Representación visual (Features)",
        options=feat_keys,
        index=feat_keys.index("hog_hsv"),
        format_func=lambda k: res["features"][k],
    )
    model_key = c_sel2.selectbox(
        "2. Algoritmo clasificador",
        options=model_keys,
        index=model_keys.index("hgb"),
        format_func=lambda k: res["models"][k],
    )
    source_mode = c_sel3.radio("3. Origen", ["Subir imagen", "Cámara web"], horizontal=True)

    bench = res["metrics_lookup"][(feat_key, model_key)]
    st.caption(
        f"Configuración activa: **{res['features'][feat_key]}** ({bench['n_features']:,} atributos) + "
        f"**{res['models'][model_key]}** — Accuracy en test: **{bench['accuracy']*100:.2f}%** | "
        f"F1-macro: **{bench['f1_macro']:.4f}**"
    )

    img_file = (
        st.file_uploader("Sube la fotografía de un ingrediente", type=["jpg", "jpeg", "png", "webp"])
        if source_mode == "Subir imagen"
        else st.camera_input("Captura un ingrediente con la cámara")
    )

    if img_file is not None:
        pil_img = Image.open(img_file)
        out = run_inference(pil_img, feat_key, model_key, res)

        col_l, col_r = st.columns([2, 3])
        with col_l:
            st.image(pil_img, caption="Imagen original", use_container_width=True)
            with st.expander("🔬 Qué ve el extractor seleccionado", expanded=True):
                vis = out["visuals"]
                if "rgb_32" in vis:
                    st.image(vis["rgb_32"], caption="Raw RGB reescalada a 32×32 (3.072 valores)", use_container_width=True)
                elif feat_key == "gray_blur":
                    st.image(vis["gray_blur"], caption="Grayscale + Gaussian Blur 64×64 (4.096 valores)", use_container_width=True)
                elif feat_key == "hog":
                    v1, v2 = st.columns(2)
                    v1.image(vis["gray_blur"], caption="Gray + Blur", use_container_width=True)
                    v2.image(vis["hog_img"], caption="Gradientes HOG", use_container_width=True)
                else:
                    v1, v2 = st.columns(2)
                    v1.image(vis["gray_blur"], caption="Gray + Blur", use_container_width=True)
                    v2.image(vis["hog_img"], caption="Gradientes HOG", use_container_width=True)
                    fig_h = px.bar(
                        x=list(range(len(vis["hue_hist"]))),
                        y=vis["hue_hist"],
                        labels={"x": "Bin de Matiz (Hue HSV)", "y": "Frecuencia"},
                        height=180,
                    )
                    fig_h.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig_h, use_container_width=True)

        with col_r:
            st.success(f"### Ingrediente detectado: **{out['pred_es'].capitalize()}** (`{out['pred_en']}`)")
            k1, k2, k3 = st.columns(3)
            k1.metric("Confianza", f"{out['confidence']*100:.1f}%")
            k2.metric("Latencia total en vivo", f"{out['total_ms']} ms")
            k3.metric("Atributos extraídos", f"{out['n_features']:,}")

            if st.button(f"➕ Añadir '{out['pred_es']}' a Mi Nevera", type="primary"):
                if out["pred_es"] not in st.session_state.basket:
                    st.session_state.basket.append(out["pred_es"])
                    st.toast(f"'{out['pred_es']}' guardado en Mi Nevera.")
                    st.rerun()

            st.subheader("Distribución Top-5 de probabilidades")
            top5 = out["probs_df"].head(5).sort_values("confianza", ascending=True)
            fig_p = px.bar(
                top5,
                x="confianza",
                y="ingrediente_es",
                orientation="h",
                text=top5["confianza"].map(lambda v: f"{v*100:.1f}%"),
                color="confianza",
                color_continuous_scale="Teal",
            )
            fig_p.update_layout(xaxis_tickformat=".0%", yaxis_title="", xaxis_title="Probabilidad estimada")
            st.plotly_chart(fig_p, use_container_width=True)


# -------------------- VISTA 2: COMPARADOR DE MODELOS EN VIVO --------------------
elif page == "⚔️ Comparador en Vivo":
    st.header("⚔️ Comparador de Modelos en Vivo")
    st.write("Sube una única imagen y compara en tiempo real cómo responden distintos extractores y algoritmos.")

    mode = st.radio(
        "Modo de comparación",
        [
            "Comparar los 7 algoritmos sobre un mismo extractor",
            "Comparar los 4 extractores sobre un mismo algoritmo",
            "Comparación personalizada (elegir combinaciones)",
        ],
        horizontal=True,
    )

    feat_keys = list(res["features"].keys())
    model_keys = list(res["models"].keys())
    pairs_to_run = []

    if mode == "Comparar los 7 algoritmos sobre un mismo extractor":
        fk = st.selectbox(
            "Extractor fijo para todos los algoritmos",
            options=feat_keys,
            index=feat_keys.index("hog_hsv"),
            format_func=lambda k: res["features"][k],
        )
        pairs_to_run = [(fk, mk) for mk in model_keys]

    elif mode == "Comparar los 4 extractores sobre un mismo algoritmo":
        mk = st.selectbox(
            "Algoritmo fijo para todos los extractores",
            options=model_keys,
            index=model_keys.index("svm"),
            format_func=lambda k: res["models"][k],
        )
        pairs_to_run = [(fk, mk) for fk in feat_keys]

    else:
        c1, c2 = st.columns(2)
        sel_feats = c1.multiselect(
            "Extractores a incluir",
            options=feat_keys,
            default=["raw_rgb", "hog", "hog_hsv"],
            format_func=lambda k: res["features"][k],
        )
        sel_models = c2.multiselect(
            "Algoritmos a incluir",
            options=model_keys,
            default=["svm", "rf", "mlp", "hgb"],
            format_func=lambda k: res["models"][k],
        )
        pairs_to_run = [(fk, mk) for fk in sel_feats for mk in sel_models]

    img_file = st.file_uploader("Imagen de prueba para la comparativa en vivo", type=["jpg", "jpeg", "png", "webp"], key="cmp_up")

    if img_file is not None and pairs_to_run:
        pil_img = Image.open(img_file)
        col_img, col_res = st.columns([1, 3])
        col_img.image(pil_img, caption="Imagen evaluada", use_container_width=True)

        rows = []
        for fk, mk in pairs_to_run:
            out = run_inference(pil_img, fk, mk, res)
            bench = res["metrics_lookup"][(fk, mk)]
            rows.append(
                {
                    "Combinación": f"{res['models'][mk]} | {res['features'][fk]}",
                    "Extractor": res["features"][fk],
                    "Algoritmo": res["models"][mk],
                    "Predicción (ES)": out["pred_es"].capitalize(),
                    "Confianza (%)": round(out["confidence"] * 100, 1),
                    "Latencia en vivo (ms)": out["total_ms"],
                    "Accuracy Test (%)": round(bench["accuracy"] * 100, 2),
                }
            )

        df_live = pd.DataFrame(rows)
        counts = df_live["Predicción (ES)"].value_counts()
        top_vote, top_n = counts.index[0], int(counts.iloc[0])

        with col_res:
            st.info(f"**Consenso en vivo:** **{top_n} de {len(df_live)}** configuraciones coinciden en **{top_vote}**.")
            st.dataframe(df_live.drop(columns=["Combinación"]), use_container_width=True, hide_index=True)

        g1, g2 = st.columns(2)
        with g1:
            st.subheader("Predicción y confianza por configuración")
            fig_conf = px.bar(
                df_live,
                x="Confianza (%)",
                y="Combinación",
                color="Predicción (ES)",
                orientation="h",
                text="Predicción (ES)",
            )
            fig_conf.update_layout(yaxis_title="")
            st.plotly_chart(fig_conf, use_container_width=True)

        with g2:
            st.subheader("Latencia de inferencia en vivo (ms)")
            fig_lat = px.bar(
                df_live.sort_values("Latencia en vivo (ms)", ascending=True),
                x="Latencia en vivo (ms)",
                y="Combinación",
                orientation="h",
                text="Latencia en vivo (ms)",
                color="Latencia en vivo (ms)",
                color_continuous_scale="Blues",
            )
            fig_lat.update_layout(yaxis_title="")
            st.plotly_chart(fig_lat, use_container_width=True)


# -------------------- VISTA 3: MI NEVERA Y RECETAS --------------------
elif page == "🍳 Mi Nevera y Recetas":
    st.header("🍳 Mi Nevera y Recomendador de Recetas")

    all_vocab = sorted(res["vectorizer"].vocabulary_.keys())
    selected_ings = st.multiselect(
        "Ingredientes disponibles en tu nevera",
        options=all_vocab,
        default=[i for i in st.session_state.basket if i in all_vocab],
    )
    st.session_state.basket = selected_ings

    f1, f2, f3 = st.columns(3)
    max_missing = f1.slider("Máx. ingredientes faltantes", 0, 10, 3)
    top_k = f2.slider("Número de recetas", 1, 15, 5)
    categories = ["Todas"] + sorted(set(res["categories"]))
    cat_sel = f3.selectbox("Categoría culinaria", categories)

    if st.button("✨ Buscar recetas compatibles", type="primary", disabled=len(selected_ings) == 0):
        recs, lat_ms = recommend_recipes(
            selected_ings,
            res,
            max_missing=max_missing,
            top_k=top_k,
            category=None if cat_sel == "Todas" else cat_sel,
        )
        st.caption(f"Consultadas **{len(res['recipes_df']):,} recetas** en **{lat_ms} ms**.")

        if not recs:
            st.warning("No se encontraron recetas con ese filtro. Prueba a subir el máximo de faltantes.")
        for rec in recs:
            with st.expander(
                f"🍽️ {rec['title']} — **{rec['match_pct']}% cobertura** | Similitud: {rec['cosine_sim']} | Faltan: {len(rec['missing'])}"
            ):
                col_a, col_b = st.columns(2)
                col_a.markdown(f"**Tienes:** {', '.join(rec['matched'])}")
                col_b.markdown(
                    f"**Faltan:** {', '.join(rec['missing']) if rec['missing'] else '¡Nada! Tienes todos los ingredientes'}"
                )
                st.markdown("**Instrucciones:**")
                st.write(rec["instructions"])
                if rec.get("source_url"):
                    st.markdown(f"[Ver fuente original]({rec['source_url']})")


# -------------------- VISTA 4: EVALUACIÓN Y MÉTRICAS --------------------
elif page == "📊 Evaluación y Métricas":
    st.header("📊 Evaluación Experimental del Sistema")
    df_all = pd.DataFrame(res["zoo_metrics"]["results"])
    best_row = df_all.sort_values("f1_macro", ascending=False).iloc[0]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Mejor Accuracy (Test)", f"{best_row['accuracy']*100:.2f}%", delta=best_row["model_label"])
    k2.metric("Mejor Representación", best_row["feature_label"], delta=f"{best_row['n_features']} atributos")
    k3.metric("Combinaciones Evaluadas", f"{len(df_all)}", delta="4 features × 7 modelos")
    k4.metric("Corpus de Recetas", f"{len(res['recipes_df']):,}", delta=f"{res['rec_metrics'].get('avg_latency_ms', 0):.2f} ms/consulta")

    st.divider()

    # 1. Heatmap completo 4 Features x 7 Modelos
    st.subheader("Mapa de Calor: Accuracy (%) — Features × Algoritmos")
    pivot_acc = df_all.pivot(index="model_label", columns="feature_label", values="accuracy") * 100
    fig_hm = px.imshow(
        pivot_acc.round(2),
        text_auto=True,
        color_continuous_scale="Teal",
        aspect="auto",
        labels={"x": "Extractor de Características", "y": "Algoritmo", "color": "Accuracy (%)"},
    )
    st.plotly_chart(fig_hm, use_container_width=True)

    # 2. Trade-off Precisión vs Velocidad + Selector de Matriz de Confusión
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Compromiso Precisión vs. Velocidad de Predicción")
        df_plot = df_all.copy()
        df_plot["total_ms_img"] = (df_plot["extract_ms_img"] + df_plot["pred_ms_img"]).round(3)
        fig_sc = px.scatter(
            df_plot,
            x="total_ms_img",
            y="accuracy",
            color="feature_label",
            symbol="model_label",
            size="n_features",
            hover_data=["model_label", "feature_label", "f1_macro", "train_s"],
            labels={"total_ms_img": "Latencia total por imagen (ms)", "accuracy": "Accuracy en Test"},
        )
        st.plotly_chart(fig_sc, use_container_width=True)

    with c2:
        st.subheader("Matriz de Confusión Interactiva")
        m_c1, m_c2 = st.columns(2)
        cm_fk = m_c1.selectbox(
            "Extractor",
            options=list(res["features"].keys()),
            index=list(res["features"].keys()).index("hog_hsv"),
            format_func=lambda k: res["features"][k],
            key="cm_fk",
        )
        cm_mk = m_c2.selectbox(
            "Algoritmo",
            options=list(res["models"].keys()),
            index=list(res["models"].keys()).index("hgb"),
            format_func=lambda k: res["models"][k],
            key="cm_mk",
        )
        cm_row = res["metrics_lookup"][(cm_fk, cm_mk)]
        classes_es = [res["en_to_es"].get(c, c) for c in res["classes"]]
        fig_cm = px.imshow(
            cm_row["confusion_matrix"],
            x=classes_es,
            y=classes_es,
            text_auto=True,
            color_continuous_scale="Blues",
            aspect="auto",
            labels={"x": "Predicho", "y": "Real"},
        )
        st.plotly_chart(fig_cm, use_container_width=True)

    # 3. Embudo de limpieza del recetario
    rec_m = res["rec_metrics"]
    if rec_m and "funnel" in rec_m:
        st.subheader("Embudo de Preparación del Recetario (TF-IDF)")
        funnel = rec_m["funnel"]
        df_f = pd.DataFrame(
            {
                "Etapa": ["Brutas", "Sin nulos", "Culinarias", "Títulos únicos", "Final (>=2 ing.)"],
                "Recetas": [
                    funnel["raw"],
                    funnel["non_null"],
                    funnel["culinary"],
                    funnel["unique_titles"],
                    funnel["final_recipes"],
                ],
            }
        )
        st.plotly_chart(px.funnel(df_f, x="Recetas", y="Etapa"), use_container_width=True)