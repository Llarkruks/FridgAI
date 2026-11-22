import io
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from PIL import Image, ImageDraw

st.set_page_config(
    page_title="Smart Fridge RAIA",
    page_icon="🧊",
    layout="wide",
)

# -------------------- CONFIGURACIÓN Y SESIÓN --------------------
if "api_url" not in st.session_state:
    st.session_state.api_url = "http://127.0.0.1:8000"
if "token" not in st.session_state:
    st.session_state.token = None
if "username" not in st.session_state:
    st.session_state.username = None


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.token}"} if st.session_state.token else {}


def api_request(method: str, path: str, **kwargs):
    url = f"{st.session_state.api_url.rstrip('/')}{path}"
    headers = kwargs.pop("headers", {})
    headers.update(auth_headers())
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        return resp
    except requests.RequestException as exc:
        st.error(f"Error de conexión con FastAPI ({url}): {exc}")
        return None


def draw_detections(image_bytes: bytes, detections: list) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        label = f"{det['ingredient_es']} ({det['confidence']*100:.0f}%)"
        draw.rectangle([x1, y1, x2, y2], outline="#00E676", width=3)
        text_y = max(0, y1 - 18)
        draw.rectangle([x1, text_y, x1 + len(label) * 7 + 8, text_y + 18], fill="#00E676")
        draw.text((x1 + 4, text_y + 2), label, fill="#000000")
    return img


# -------------------- BARRA LATERAL (LOGIN + NAVEGACIÓN) --------------------
with st.sidebar:
    st.title("🧊 Smart Fridge RAIA")
    st.session_state.api_url = st.text_input("URL del Backend FastAPI", st.session_state.api_url)

    # Comprobar estado del servidor
    health_resp = api_request("GET", "/health")
    if health_resp and health_resp.status_code == 200:
        h = health_resp.json()
        st.success(f"API Online | {h['recipes_loaded']:,} recetas | {h['visual_classes']} clases")
    else:
        st.warning("Backend desconectado. Arranca Uvicorn en el puerto 8000.")

    st.divider()

    if not st.session_state.token:
        st.subheader("Iniciar Sesión")
        tab_login, tab_reg = st.tabs(["Entrar", "Registro"])
        with tab_login:
            u = st.text_input("Usuario", value="demo", key="login_u")
            p = st.text_input("Contraseña", value="demo1234", type="password", key="login_p")
            if st.button("Acceder", use_container_width=True):
                r = api_request("POST", "/token", data={"username": u, "password": p})
                if r and r.status_code == 200:
                    st.session_state.token = r.json()["access_token"]
                    st.session_state.username = u
                    st.rerun()
                elif r:
                    st.error(r.json().get("detail", "Credenciales incorrectas"))
        with tab_reg:
            ru = st.text_input("Nuevo usuario", key="reg_u")
            rp = st.text_input("Nueva contraseña (mín. 6)", type="password", key="reg_p")
            if st.button("Crear cuenta", use_container_width=True):
                r = api_request("POST", "/register", json={"username": ru, "password": rp})
                if r and r.status_code == 201:
                    st.success("Usuario creado. Ya puedes iniciar sesión.")
                elif r:
                    st.error(r.json().get("detail", "No se pudo registrar"))
    else:
        st.info(f"Sesión activa: **{st.session_state.username}**")
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.token = None
            st.session_state.username = None
            st.rerun()

    st.divider()
    page = st.radio(
        "Navegación",
        [
            "📷 Escáner Visual (YOLO)",
            "🥬 Mi Nevera",
            "🍳 Recetas y Favoritos",
            "📊 Dashboard ML",
        ],
    )


# -------------------- PÁGINA 1: ESCÁNER VISUAL --------------------
if page == "📷 Escáner Visual (YOLO)":
    st.header("📷 Escáner de Ingredientes con YOLOv8n")
    if not st.session_state.token:
        st.warning("Inicia sesión en la barra lateral (`demo` / `demo1234`) para escanear.")
        st.stop()

    col_cfg1, col_cfg2 = st.columns([2, 1])
    with col_cfg1:
        source_mode = st.radio("Origen de la imagen", ["Subir foto", "Cámara web"], horizontal=True)
    with col_cfg2:
        conf = st.slider("Umbral de confianza", 0.10, 0.90, 0.35, 0.05)

    img_file = (
        st.file_uploader("Sube una foto del frigorífico", type=["jpg", "jpeg", "png", "webp"])
        if source_mode == "Subir foto"
        else st.camera_input("Captura desde tu cámara")
    )

    if img_file is not None:
        raw_bytes = img_file.getvalue()
        if st.button("🔍 Detectar ingredientes", type="primary"):
            with st.spinner("Ejecutando inferencia YOLOv8n en FastAPI..."):
                r = api_request(
                    "POST",
                    f"/recognize?conf={conf}",
                    files={"image": (img_file.name, raw_bytes, img_file.type or "image/jpeg")},
                )
            if r and r.status_code == 200:
                st.session_state["last_scan"] = (raw_bytes, r.json())
            elif r:
                st.error(r.json().get("detail", "Error en la detección"))

    if "last_scan" in st.session_state:
        raw_bytes, res = st.session_state["last_scan"]
        dets = res["detected_items"]
        c1, c2 = st.columns([3, 2])
        with c1:
            annotated = draw_detections(raw_bytes, dets)
            st.image(annotated, caption=f"Inferencia: {res['inference_ms']} ms | {len(dets)} detecciones", use_container_width=True)
        with c2:
            st.subheader("Ingredientes detectados")
            if not dets:
                st.info("No se detectaron ingredientes por encima del umbral.")
            else:
                df_det = pd.DataFrame(dets)[["ingredient_es", "class_en", "confidence"]]
                st.dataframe(df_det, use_container_width=True, hide_index=True)

                unique_ings = sorted({d["ingredient_es"] for d in dets})
                selected = st.multiselect("Seleccionar para añadir a Mi Nevera", unique_ings, default=unique_ings)
                if st.button("➕ Guardar seleccionados en Mi Nevera", use_container_width=True):
                    added = 0
                    for ing in selected:
                        resp = api_request(
                            "POST",
                            "/fridge/items",
                            json={"ingredient_es": ing, "source": "camera", "quantity": 1},
                        )
                        if resp and resp.status_code == 201:
                            added += 1
                    st.success(f"{added} ingredientes guardados en tu nevera.")


# -------------------- PÁGINA 2: MI NEVERA (CRUD) --------------------
elif page == "🥬 Mi Nevera":
    st.header("🥬 Inventario de Mi Nevera")
    if not st.session_state.token:
        st.warning("Inicia sesión en la barra lateral para gestionar tu nevera.")
        st.stop()

    with st.form("add_manual_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 1, 2, 1])
        ing_name = c1.text_input("Ingrediente (en español, ej. tomate, pollo, huevo)")
        qty = c2.number_input("Cantidad", min_value=1, max_value=99, value=1)
        src = c3.selectbox("Origen", ["manual", "camera", "pantry"])
        submitted = c4.form_submit_button("Añadir", use_container_width=True)
        if submitted and ing_name.strip():
            r = api_request(
                "POST",
                "/fridge/items",
                json={"ingredient_es": ing_name.strip().lower(), "source": src, "quantity": int(qty)},
            )
            if r and r.status_code == 201:
                st.success(f"Añadido: {ing_name}")
                st.rerun()

    r = api_request("GET", "/fridge/items")
    items = r.json() if (r and r.status_code == 200) else []

    if not items:
        st.info("Tu nevera está vacía. Escanea una foto o añade ingredientes arriba.")
    else:
        for item in items:
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
            col1.markdown(f"**{item['ingredient_es'].capitalize()}** `{item['source']}`")
            new_q = col2.number_input(
                "Cant.",
                min_value=1,
                max_value=99,
                value=item["quantity"],
                key=f"qty_{item['id']}",
                label_visibility="collapsed",
            )
            if col3.button("💾", key=f"save_{item['id']}", help="Actualizar cantidad"):
                api_request("PUT", f"/fridge/items/{item['id']}", json={"quantity": int(new_q)})
                st.rerun()
            if col4.button("🗑️", key=f"del_{item['id']}", help="Eliminar"):
                api_request("DELETE", f"/fridge/items/{item['id']}")
                st.rerun()


# -------------------- PÁGINA 3: RECETAS Y FAVORITOS --------------------
elif page == "🍳 Recetas y Favoritos":
    st.header("🍳 Recomendador de Recetas (TF-IDF + Coseno)")
    if not st.session_state.token:
        st.warning("Inicia sesión en la barra lateral para ver recomendaciones y favoritos.")
        st.stop()

    tab_rec, tab_fav = st.tabs(["🔎 Recomendar desde Mi Nevera", "⭐ Mis Favoritos"])

    with tab_rec:
        cats_r = api_request("GET", "/categories")
        categories = ["Todas"] + (cats_r.json() if (cats_r and cats_r.status_code == 200) else [])

        f1, f2, f3 = st.columns(3)
        max_missing = f1.slider("Máx. ingredientes faltantes", 0, 10, 3)
        top_k = f2.slider("Número de recetas", 1, 15, 5)
        cat_sel = f3.selectbox("Categoría", categories)

        params = {"max_missing": max_missing, "top_k": top_k}
        if cat_sel != "Todas":
            params["category"] = cat_sel

        if st.button("✨ Buscar recetas", type="primary"):
            r = api_request("GET", "/recommend/from-fridge", params=params)
            if r and r.status_code == 200:
                st.session_state["last_recs"] = r.json()
            elif r:
                st.warning(r.json().get("detail", "No se pudieron obtener recetas."))

        for rec in st.session_state.get("last_recs", []):
            with st.expander(
                f"🍽️ {rec['title']} — **{rec['match_pct']}% cobertura** | Sim: {rec['cosine_sim']} | Faltan: {len(rec['missing_ingredients'])}"
            ):
                m1, m2 = st.columns(2)
                m1.markdown(f"**Tienes:** {', '.join(rec['matched_ingredients'])}")
                m2.markdown(
                    f"**Faltan:** {', '.join(rec['missing_ingredients']) if rec['missing_ingredients'] else '¡Nada! Tienes todo'}"
                )
                st.markdown("**Instrucciones:**")
                st.write(rec["instructions"])
                if rec.get("source_url"):
                    st.markdown(f"[Ver receta original]({rec['source_url']})")
                if st.button("⭐ Guardar en Favoritos", key=f"fav_btn_{rec['recipe_id']}"):
                    fr = api_request("POST", "/favorites", json={"recipe_id": rec["recipe_id"], "notes": ""})
                    if fr and fr.status_code == 201:
                        st.success("Guardada en favoritos.")

    with tab_fav:
        fr = api_request("GET", "/favorites")
        favs = fr.json() if (fr and fr.status_code == 200) else []
        if not favs:
            st.info("Aún no tienes recetas favoritas guardadas.")
        for fav in favs:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"⭐ **{fav['dish_title']}** *(guardada el {fav['saved_at'][:10]})*")
            if c2.button("Eliminar", key=f"delfav_{fav['id']}"):
                api_request("DELETE", f"/favorites/{fav['id']}")
                st.rerun()


# -------------------- PÁGINA 4: DASHBOARD ML --------------------
elif page == "📊 Dashboard ML":
    st.header("📊 Laboratorio y Métricas de Machine Learning")
    r = api_request("GET", "/ml/metrics")
    if not r or r.status_code != 200:
        st.error("No se pudieron cargar las métricas desde `/ml/metrics`.")
        st.stop()

    metrics = r.json()

    # 1. KPIs principales
    yolo = metrics.get("yolo", {})
    classic = metrics.get("classic_ml", {})
    rec_m = metrics.get("recommender", {})

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("YOLOv8n mAP@50 (31 clases)", f"{yolo.get('mAP50', 0)*100:.2f}%")
    k2.metric("Mejor ML Clásico (12 clases)", "72.90%", delta="HistGradientBoosting")
    k3.metric("Inferencia YOLO (GPU T4)", f"{yolo.get('speed_ms', {}).get('inference', 0):.2f} ms")
    k4.metric("Latencia Recomendador TF-IDF", f"{rec_m.get('avg_latency_ms', 0):.2f} ms")

    st.divider()

    # 2. Comparativa 7 modelos clásicos + Ablación
    if classic:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Comparativa 7 Modelos Clásicos (5-Fold CV)")
            df_cv = pd.DataFrame(classic["cv_comparison"]).sort_values("f1_macro", ascending=True)
            fig_cv = px.bar(
                df_cv,
                x="f1_macro",
                y="model",
                orientation="h",
                text="f1_macro",
                color="f1_macro",
                color_continuous_scale="Teal",
            )
            st.plotly_chart(fig_cv, use_container_width=True)

        with c2:
            st.subheader("Estudio de Ablación de Features (SVM RBF)")
            df_ab = pd.DataFrame.from_dict(classic["ablation"], orient="index").reset_index()
            df_ab.columns = ["Feature", "n_features", "accuracy", "f1_macro", "train_s", "pred_s"]
            fig_ab = px.bar(
                df_ab,
                x="Feature",
                y="accuracy",
                text="accuracy",
                color="accuracy",
                color_continuous_scale="Blues",
            )
            st.plotly_chart(fig_ab, use_container_width=True)

        st.subheader("Matriz de Confusión — HistGradientBoosting (Top-12)")
        fig_cm = px.imshow(
            classic["confusion_matrix"],
            x=classic["classes"],
            y=classic["classes"],
            text_auto=True,
            color_continuous_scale="Blues",
            aspect="auto",
        )
        st.plotly_chart(fig_cm, use_container_width=True)

    # 3. Embudo del Recomendador
    if rec_m:
        st.subheader("Embudo de Limpieza del Corpus de Recetas")
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