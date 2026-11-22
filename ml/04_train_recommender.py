import os
import re
import json
import time
import pickle
import unicodedata
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Rutas automáticas desde C:\4rt\RAIA\Proyecto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
csv_files = list(PROJECT_ROOT.rglob("recipes.csv"))
if not csv_files:
    raise FileNotFoundError(
        f"No se encontró 'recipes.csv' dentro de {PROJECT_ROOT}. "
        "Coloca el archivo recipes.csv dentro de la carpeta Proyecto (p. ej. en datasets/)."
    )

RAW_CSV = csv_files[0]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
print("Dataset de recetas detectado en:", RAW_CSV)

# 1. Mapa oficial EN (data.yaml) -> ES (27 clases útiles; se excluyen date, lamb, bulgur, okra)
YOLO_TO_ES = {
    "apple": "manzana", "banana": "platano", "beans": "alubia", "beef": "ternera",
    "bread": "pan", "butter": "mantequilla", "cabbage": "col", "carrot": "zanahoria",
    "cheese": "queso", "chicken": "pollo", "chickpea": "garbanzo", "cucumber": "pepino",
    "eggplant": "berenjena", "eggs": "huevo", "fish": "pescado", "garlic": "ajo",
    "lemon": "limon", "lentil": "lenteja", "lettuce": "lechuga", "milk": "leche",
    "onion": "cebolla", "orange": "naranja", "potato": "patata", "rice": "arroz",
    "spinach": "espinaca", "tomato": "tomate", "yogurt": "yogur",
}

# Básicos de despensa (gestionables como casillas fijas en Streamlit)
PANTRY_BASICS = {
    "sal": r"\bsal\b", "aceite": r"\baceite\b", "agua": r"\bagua\b",
    "azucar": r"\bazucar\b", "pimienta": r"\bpimienta\b", "harina": r"\bharina\b",
    "vinagre": r"\bvinagre\b",
}

# Vocabulario culinario canónico (27 visuales + 30 frecuentes para detectar faltantes reales)
INGREDIENT_VOCAB = {
    "manzana": r"\bmanzanas?\b",
    "platano": r"\bplatanos?\b|\bbananas?\b",
    "alubia": r"\balubias?\b|\bjudias?\b|\bfrijoles?\b|\bporotos?\b|\bhabichuelas?\b",
    "ternera": r"\bternera\b|\bcarne\b|\bvacuno\b|\bbistec\b|\bchurrasco\b|\bentrecot\b|\bsolomillo\b",
    "pan": r"\bpan\b|\bpanes\b",
    "mantequilla": r"\bmantequilla\b|\bmargarina\b",
    "col": r"\bcol\b|\brepollo\b",
    "zanahoria": r"\bzanahorias?\b",
    "queso": r"\bquesos?\b|\bmozzarella\b|\bparmesano\b|\bcheddar\b",
    "pollo": r"\bpollo\b|\bpechugas?\b|\bmuslos?\b",
    "garbanzo": r"\bgarbanzos?\b",
    "pepino": r"\bpepinos?\b",
    "berenjena": r"\bberenjenas?\b",
    "huevo": r"\bhuevos?\b|\byemas?\b|\bclaras?\b",
    "pescado": r"\bpescado\b|\bmerluza\b|\bbacalao\b|\bsalmon\b|\batun\b|\blubina\b|\bdorada\b|\brape\b|\btrucha\b|\bsardinas?\b",
    "ajo": r"\bajos?\b",
    "limon": r"\blimon(?:es)?\b",
    "lenteja": r"\blentejas?\b",
    "lechuga": r"\blechugas?\b|\brucula\b|\bcanonigos\b",
    "leche": r"\bleche\b",
    "cebolla": r"\bcebollas?\b|\bcebolletas?\b|\bcebollin\b",
    "naranja": r"\bnaranjas?\b",
    "patata": r"\bpatatas?\b|\bpapas?\b",
    "arroz": r"\barroz\b",
    "espinaca": r"\bespinacas?\b|\bacelgas?\b",
    "tomate": r"\btomates?\b|\bjitomates?\b",
    "yogur": r"\byogur(?:es|t)?\b",
    # Ingredientes frecuentes no visuales (para informar faltantes reales al usuario)
    "pimiento": r"\bpimientos?\b|\bmorron(?:es)?\b",
    "nata": r"\bnata\b|\bcrema de leche\b",
    "pasta": r"\bpasta\b|\bespaguetis?\b|\bmacarrones?\b|\bfideos?\b|\btallarines?\b|\blasana\b",
    "cerdo": r"\bcerdo\b|\blomo\b|\bcostillas?\b",
    "champinon": r"\bchampinon(?:es)?\b|\bsetas?\b|\bhongos?\b",
    "jamon": r"\bjamon\b",
    "bacon": r"\bbacon\b|\btocino\b|\bpanceta\b|\btocineta\b",
    "gamba": r"\bgambas?\b|\bcamaron(?:es)?\b|\blangostinos?\b",
    "calabacin": r"\bcalabacin(?:es)?\b|\bzucchini\b",
    "aguacate": r"\baguacates?\b|\bpaltas?\b",
    "puerro": r"\bpuerros?\b",
    "apio": r"\bapio\b",
    "guisante": r"\bguisantes?\b|\barvejas?\b",
    "calabaza": r"\bcalabazas?\b|\bzapallo\b",
    "chocolate": r"\bchocolate\b|\bcacao\b",
    "fresa": r"\bfresas?\b|\bfrutillas?\b",
    "pina": r"\bpina\b|\banana\b",
    "aceituna": r"\baceitunas?\b|(?<!aceite de )\bolivas?\b",
    "maiz": r"(?<!harina de )(?<!almidon de )(?<!aceite de )(?<!fecula de )\b(?:maiz|choclo|elote)\b",
    "chorizo": r"\bchorizos?\b|\bsalchichas?\b|\bchistorra\b|\blonganiza\b",
    "hojaldre": r"\bhojaldre\b|\bmasa quebrada\b|\bmasa brisa\b",
    "perejil": r"\bperejil\b|\bcilantro\b|\balbahaca\b",
    "vino": r"\bvino\b",
    "caldo": r"\bcaldo\b",
    "mayonesa": r"\bmayonesa\b",
    "levadura": r"\blevadura\b|\bpolvo de hornear\b",
    "canela": r"\bcanela\b",
    "miel": r"\bmiel\b",
    "almendra": r"\balmendras?\b|\bnueces\b|\bnuez\b|\bavellanas?\b",
    "curry": r"\bcurry\b|\bcurcuma\b",
}

def normalize_text(text: str) -> str:
    text = str(text).lower()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)   # Separa tokens pegados como "oliva1"
    text = re.sub(r"(\d)([a-z])", r"\1 \2", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# 2. Carga y limpieza (Manage Data)
df_raw = pd.read_csv(RAW_CSV, sep=";", encoding="utf-8")
n_raw = len(df_raw)

df = df_raw.dropna(subset=["Recipe_ingredients", "Recipe"]).copy()
n_non_null = len(df)

df = df[~df["Recipe_category"].isin(["Consejos de cocina", "Cócteles y bebidas"])].copy()
n_culinary = len(df)

df = df.drop_duplicates(subset=["Dish_Title"]).reset_index(drop=True)
n_dedup = len(df)

compiled_vocab = {k: re.compile(v) for k, v in INGREDIENT_VOCAB.items()}
compiled_pantry = {k: re.compile(v) for k, v in PANTRY_BASICS.items()}

df["ing_norm"] = df["Recipe_ingredients"].apply(normalize_text)
df["parsed_ingredients"] = df["ing_norm"].apply(lambda t: [k for k, p in compiled_vocab.items() if p.search(t)])
df["parsed_pantry"] = df["ing_norm"].apply(lambda t: [k for k, p in compiled_pantry.items() if p.search(t)])
df["n_ingredients"] = df["parsed_ingredients"].apply(len)

df_model = df[df["n_ingredients"] >= 2].reset_index(drop=True)
df_model["recipe_id"] = df_model.index

print(f"\n--- EMBUDO DE LIMPIEZA (Manage Data) ---")
print(f"Brutas: {n_raw} -> Sin nulos: {n_non_null} -> Culinarias: {n_culinary} -> Sin duplicados: {n_dedup} -> >=2 ing.: {len(df_model)}")
print(f"Media de ingredientes por receta: {df_model['n_ingredients'].mean():.2f} (std: {df_model['n_ingredients'].std():.2f}, mediana: {df_model['n_ingredients'].median():.0f})")

# 3. Vectorización TF-IDF (Train)
corpus = df_model["parsed_ingredients"].apply(lambda lst: " ".join(lst))
vectorizer = TfidfVectorizer()
tfidf_matrix = vectorizer.fit_transform(corpus)

# 4. Guardar artefactos serializados para FastAPI (Deploy Model)
cols_to_save = [
    "recipe_id", "Dish_Title", "Recipe_category", "Recipe_subcategory",
    "Recipe_ingredients", "Recipe", "Source", "parsed_ingredients", "parsed_pantry",
]
df_model[cols_to_save].to_parquet(PROCESSED_DIR / "recipes_clean.parquet", index=False)

with open(ARTIFACTS_DIR / "tfidf_vectorizer.pkl", "wb") as f:
    pickle.dump(vectorizer, f)
sparse.save_npz(ARTIFACTS_DIR / "tfidf_matrix.npz", tfidf_matrix)

with open(ARTIFACTS_DIR / "mappings.json", "w", encoding="utf-8") as f:
    json.dump(
        {"yolo_to_es": YOLO_TO_ES, "pantry_basics": list(PANTRY_BASICS.keys())},
        f,
        indent=2,
        ensure_ascii=False,
    )

# Guardar métricas del recomendador para el Dashboard ML de Streamlit
tfidf_means = np.asarray(tfidf_matrix.mean(axis=0)).flatten()
vocab_terms = vectorizer.get_feature_names_out()
top_tfidf_terms = {
    vocab_terms[i]: round(float(tfidf_means[i]), 5)
    for i in np.argsort(tfidf_means)[::-1][:30]
}

# 5. Evaluación con 3 consultas reales de frigorífico
titles = df_model["Dish_Title"].tolist()
categories = df_model["Recipe_category"].tolist()
ing_sets = [set(lst) for lst in df_model["parsed_ingredients"]]

def recommend_test(user_ingredients, max_missing=2, top_k=5):
    t0 = time.perf_counter()
    user_set = set(user_ingredients)
    q_vec = vectorizer.transform([" ".join(user_set)])
    sims = cosine_similarity(q_vec, tfidf_matrix).flatten()
    pool = min(300, len(sims))
    top_idx = np.argpartition(sims, -pool)[-pool:]

    results = []
    for idx in top_idx:
        sim = float(sims[idx])
        if sim <= 0:
            continue
        rec_ings = ing_sets[idx]
        matched = rec_ings & user_set
        missing = rec_ings - user_set
        if len(missing) > max_missing:
            continue
        cov = len(matched) / len(rec_ings)
        score = 0.6 * cov + 0.4 * sim
        results.append({
            "recipe_id": int(idx),
            "title": titles[idx],
            "category": categories[idx],
            "match_pct": round(cov * 100, 1),
            "cosine_sim": round(sim, 4),
            "score": round(score, 4),
            "matched": sorted(matched),
            "missing": sorted(missing),
        })
    results.sort(key=lambda x: (x["score"], -len(x["missing"])), reverse=True)
    return results[:top_k], (time.perf_counter() - t0) * 1000

print(f"\n--- EVALUACIÓN DEL RECOMENDADOR (TF-IDF {tfidf_matrix.shape}) ---")
latencies = []
for query in [
    ["pollo", "cebolla", "ajo", "tomate", "patata", "zanahoria"],
    ["huevo", "patata", "cebolla", "queso"],
    ["arroz", "pollo", "cebolla", "ajo"],
]:
    recs, ms = recommend_test(query, max_missing=2, top_k=3)
    latencies.append(ms)
    print(f"\nNevera: {query} | Latencia: {ms:.2f} ms")
    for r in recs:
        print(f"  [{r['match_pct']}% | sim={r['cosine_sim']}] {r['title']} ({r['category']}) | Faltan: {r['missing']}")

with open(ARTIFACTS_DIR / "recommender_metrics.json", "w", encoding="utf-8") as f:
    json.dump({
        "funnel": {
            "raw": n_raw, "non_null": n_non_null,
            "culinary": n_culinary, "unique_titles": n_dedup,
            "final_recipes": len(df_model),
        },
        "vocab_size": len(vectorizer.vocabulary_),
        "avg_latency_ms": round(float(np.mean(latencies)), 2),
        "top_tfidf_terms": top_tfidf_terms,
    }, f, indent=2, ensure_ascii=False)

print("\nArtefactos del recomendador guardados en:", ARTIFACTS_DIR)