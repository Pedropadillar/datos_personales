from flask import Flask, render_template, request
import openai
import fitz  # PyMuPDF
import json

# --- Configuración de la aplicación Flask ---
app = Flask(__name__, template_folder="templates")

# Cliente OpenAI para LM Studio local
client = openai.OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="not-needed"
)

# Ruta principal: muestra el formulario
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

# Ruta para cancelar el proceso
@app.route('/cancelar', methods=['GET'])
def cancelar():
    return render_template('index.html', error="El proceso fue cancelado.")

# Ruta para procesar el archivo subido
def extract_text_from_file(file_bytes, mimetype):
    text = ''
    if mimetype == 'application/pdf':
        with fitz.open(stream=file_bytes, filetype='pdf') as doc:
            for page in doc:
                text += page.get_text()
    else:
        text = file_bytes.decode('utf-8', errors='replace')
    return text

@app.route('/extraer-datos/', methods=['POST'])
def extraer_datos():
    error = None
    extracted_data = ''

    file = request.files.get('file')
    if not file:
        return render_template('index.html', error="No se subió ningún archivo.")

    try:
        file_bytes = file.read()
        content_text = extract_text_from_file(file_bytes, file.mimetype)

        if not content_text.strip():
            raise ValueError("El archivo parece estar vacío o no se pudo extraer texto.")

        # Prompt que obliga a responder solo con JSON
        prompt = f"""
Por favor, extrae los siguientes datos personales del texto y responde **únicamente** con estas claves: 
- nombre_completo
- email
- telefono
- direccion_postal
- dni

Si algún dato no está presente, asigna null.

Aquí está el texto:
---
{content_text}
---
"""

        response = client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": (
                    "Eres un asistente que extrae datos personales de documentos. "
                    "Examina los documentos subidos detenidamente. Responde exclusivamente con los datos solicitados, sin ninguna explicación."
                )},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()
        try:
            # Intentar parsear JSON
            data = json.loads(raw)
            extracted_data = json.dumps(data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            # Si falla parseo, mostrar respuesta cruda
            extracted_data = raw

    except Exception as e:
        error = f"Ha ocurrido un error: {e}"

    return render_template('index.html', extracted_data=extracted_data, error=error)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
