
import json
import time
import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME = "llama3.2"


def generate_chat_response(messages, ingredients, recipes):

    start_time = time.perf_counter()

    ingredients_context = json.dumps(
        ingredients,
        ensure_ascii=False,
        default=str
    )

    recipes_context = json.dumps(
        recipes,
        ensure_ascii=False,
        default=str
    )

    system_prompt = f"""
    Eres FridgIA Assistant, un asistente inteligente de cocina.

    Tu objetivo es ayudar al usuario a preparar recetas
    aprovechando los alimentos que tiene disponibles y
    reduciendo el desperdicio alimentario.

    INVENTARIO ACTUAL DEL USUARIO:
    {ingredients_context}

    RECETAS RECUPERADAS DEL RECOMENDADOR FRIDGIA:
    {recipes_context}

    REGLAS:
    - Responde siempre en español.
    - Utiliza los ingredientes reales del inventario.
    - Prioriza las recetas recuperadas del dataset.
    - Indica claramente los ingredientes que faltan.
    - No inventes ingredientes disponibles en la nevera.
    - No inventes datos del recetario.
    - Si propones una receta que no está en el dataset,
      indica que es una sugerencia generada por la IA.
    - Si no conoces un tiempo de preparación, no lo
      presentes como un dato exacto.
    - Explica las instrucciones de forma clara y ordenada.
    - No garantices que una receta es apta para alergias.
    - Comprueba los ingredientes originales cuando estén
      disponibles, porque el recomendador utiliza un
      vocabulario limitado.
    - No asegures que una receta se puede preparar
      completamente si faltan cantidades o ingredientes.
    - Si la pregunta no está relacionada con la cocina,
      indica amablemente que eres un asistente culinario.
    """

    ollama_messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    # Añadir el historial reciente de conversación
    ollama_messages.extend(messages[-10:])

    payload = {
        "model": MODEL_NAME,
        "messages": ollama_messages,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_ctx": 8192,
            "num_predict": 512
        }
    }

    try:

        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=180
        )

        response.raise_for_status()

        result = response.json()

        answer = result["message"]["content"]

        elapsed_time = round(
            time.perf_counter() - start_time,
            2
        )

        return {
            "answer": answer,
            "model": MODEL_NAME,
            "response_time": elapsed_time
        }

    except requests.exceptions.Timeout as exc:

        raise RuntimeError(
            "Ollama ha tardado demasiado en responder."
        ) from exc

    except requests.exceptions.ConnectionError as exc:

        raise RuntimeError(
            "No se puede conectar con Ollama. "
            "Comprueba que está ejecutándose."
        ) from exc

    except requests.exceptions.HTTPError as exc:

        raise RuntimeError(
            f"Error de Ollama: {response.status_code}. "
            f"Comprueba que el modelo {MODEL_NAME} está instalado."
        ) from exc
