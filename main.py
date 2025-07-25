from flask import Flask, render_template, request, redirect, url_for, send_file, session
import openai
import fitz  # PyMuPDF
import json
import io
import csv
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import letter
from docx import Document
import threading
import time
import webbrowser
import sys, os
import tkinter as tk

app = Flask(__name__, template_folder="templates")
app.secret_key = "una_clave_secreta_que_tu_quieras"  # Necesario para sesión

client = openai.OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="not-needed"
)

def extract_text_from_file(file_bytes, mimetype):
    text = ''
    if mimetype == 'application/pdf':
        doc = fitz.open(stream=file_bytes, filetype='pdf')
        try:
            for page in doc:
                text += page.get_text() # type: ignore[reportAttributeAccessIssue]
        finally:
            doc.close()
    else:
        text = file_bytes.decode('utf-8', errors='replace')
    return text

def extract_personal_data(content_text):
    prompt = f"""
Examina detenidamente el documento subido. Extrae los siguientes datos personales del texto y responde **SOLO** con un JSON con estas claves, sin ninguna explicación ni razonamiento, sin ningún texto adicional, únicamente el JSON:
- Nombre
- Email
- Telefono
- Direccion
- DNI

Para la Dirección busca y concatena los siguientes campos del archivo con el siguiente formato de texto:
Direccion, Localidad (Código postal Provincia)

Donde pone DNI debes buscar el campo CIF/NIF/NIE/Otro y devolver el número completo.
Si algún dato no está presente, asigna null. 

Aquí está el texto:
---
{content_text}
---
"""
    response = client.chat.completions.create(
        model="deepseek-r1-0528-qwen3-8b@q8_0",
        messages=[
            {"role": "system", "content": (
                "Eres un asistente que extrae datos personales de documentos. Examina detenidamente los documentos y extrae los datos solicitados de forma precisa. "
                "Responde exclusivamente con los datos solicitados, sin ninguna explicación."
            )},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
    )
    #raw = response.choices[0].message.content.strip()
    raw = (response.choices[0].message.content or "").strip()
    #print('RESPUESTA CRUDA DEL MODELO:', raw)
    # Si hay razonamiento, intenta quedarte solo con el primer bloque JSON
    if '{' in raw and '}' in raw:
        raw_json = raw[raw.find('{'):raw.rfind('}')+1]
    else:
        raw_json = raw
    try:
        data = json.loads(raw_json)
    except Exception as e:
        print('Error al parsear JSON:', e)
        data = {"Dombre": None, "Email": None, "Telefono": None, "Direccion": None, "DNI": None}
    return data

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html', results=None, error=None)

@app.route('/cancelar', methods=['GET'])
def cancelar():
    return render_template('index.html', results=None, error="El proceso fue cancelado.")

@app.route('/extraer-datos/', methods=['POST'])
def extraer_datos(): #extraemos los datos personales
    error = None
    results = []

    files = request.files.getlist('file')
    if not files or files[0].filename == '':
        return render_template('index.html', results=None, error="No se subió ningún archivo.")

    for file in files:
        try:
            file_bytes = file.read()
            content_text = extract_text_from_file(file_bytes, file.mimetype)
            if not content_text.strip():
                raise ValueError("El archivo parece estar vacío o no se pudo extraer texto.")
            data = extract_personal_data(content_text)
            results.append({'filename': file.filename, 'data': data})
        except Exception as e:
            results.append({'filename': file.filename, 'data': {
                "nombre": None, "email": None, "telefono": None, "direccion": None, "DNI": None
            }, 'error': str(e)})

    session['results'] = results  # Guardar para exportar
    print('RESULTADOS:', results)
    return render_template('index.html', results=results, error=error)

@app.route('/exportar_csv')
def exportar_csv():

    results = session.get('results', [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Archivo', 'Nombre', 'Email', 'Teléfono', 'Dirección', 'DNI'])
    for r in results:
        d = r['data']
        direccion = d.get('Direccion')
        # Si es dict, conviértelo a string
        if isinstance(direccion, dict):
            direccion = ', '.join([f"{k}: {v}" for k, v in direccion.items()])
        writer.writerow([
            r['filename'],
            d.get('Nombre'), d.get('Email'), d.get('Telefono'),
            direccion, d.get('DNI')
        ])
    # Añade el BOM al principio para Excel
    csv_data = '\ufeff' + output.getvalue()
    return send_file(
        io.BytesIO(csv_data.encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='resultados.csv'
    )

@app.route('/exportar_pdf')
def exportar_pdf():
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.units import cm

    results = session.get('results', [])
    buffer = io.BytesIO()

    # A4 horizontal, márgenes 1.5cm
    pagesize = landscape(A4)
    page_width = 29.7*cm - 3*cm  # 29.7cm menos márgenes
    # Ajusta el ancho total de las columnas para que no se corte
    col_widths = [4*cm, 5*cm, 5*cm, 3*cm, 9*cm, 2.7*cm]  # Suma 28.7cm, cabe justo

    styles = getSampleStyleSheet()
    styleN = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontSize=8,
        leading=9,
        alignment=TA_LEFT,
        splitLongWords=True,
        wordWrap='CJK'
    )

    data = [
        [
            Paragraph('Archivo', styleN),
            Paragraph('Nombre', styleN),
            Paragraph('Email', styleN),
            Paragraph('Teléfono', styleN),
            Paragraph('Dirección', styleN),
            Paragraph('DNI', styleN)
        ]
    ]

    for r in results:
        d = r['data']
        # Dirección postal: dict => string bonito
        direccion = d.get('Direccion', '') or ''
        if isinstance(direccion, dict):
            direccion = ', '.join([f"{k}: {v}" for k, v in direccion.items()])
        else:
            direccion = str(direccion)
        # Cuidado con None
        DNI = d.get('DNI', '') or ''
        data.append([
            Paragraph(str(r['filename']), styleN),
            Paragraph(str(d.get('Nombre', '') or ''), styleN),
            Paragraph(str(d.get('Email', '') or ''), styleN),
            Paragraph(str(d.get('Telefono', '') or ''), styleN),
            Paragraph(direccion, styleN),
            Paragraph(DNI, styleN)
        ])

    doc = SimpleDocTemplate(
        buffer, pagesize=pagesize,
        rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm
    )
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1f77b4")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, None]),
    ]))
    doc.build([table])
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name='resultados.pdf',
        mimetype='application/pdf'
    )


@app.route('/exportar_docx')
def exportar_docx():
    results = session.get('results', [])
    doc = Document()
    table = doc.add_table(rows=1, cols=6)
    hdr_cells = table.rows[0].cells
    headers = ['Archivo', 'Nombre Completo', 'Email', 'Teléfono', 'Dirección Postal', 'DNI']
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
    for r in results:
        d = r['data']
        row_cells = table.add_row().cells
        row_cells[0].text = str(r['filename'])
        row_cells[1].text = str(d.get('Nombre'))
        row_cells[2].text = str(d.get('Email'))
        row_cells[3].text = str(d.get('Telefono'))
        row_cells[4].text = str(d.get('Direccion'))
        row_cells[5].text = str(d.get('DNI'))
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name='resultados.docx',
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )

def open_browser():
    # Pequeña espera para que Flask arranque
    time.sleep(1)
    webbrowser.open('http://127.0.0.1:8000')

def start_flask():
    # Arranca Flask en este hilo
    app.run(host='0.0.0.0', port=8000, debug=False)

if __name__ == '__main__':
    # 1) Lanzar servidor Flask en hilo
    threading.Thread(target=start_flask, daemon=True).start()
    # 2) Lanzar navegador en hilo
    threading.Thread(target=open_browser, daemon=True).start()

    # 3) Crear ventana tkinter para el icono y cerrar
    root = tk.Tk()
    root.title("Datos personales")
    # base_path = os.path.abspath(os.path.dirname(__file__))
    # icon_path = os.path.join(base_path, 'icono.ico')  # <— ¡Define icon_path aquí!
    # root.iconbitmap(icon_path)       # tu .ico en el mismo directorio
    root.geometry("200x80")
    tk.Label(root, text="Servidor en localhost:8000").pack(pady=10)
    tk.Button(root, text="Cerrar app", command=lambda: sys.exit(0)).pack()
    root.mainloop()

# if getattr(sys, 'frozen', False):
#     # Aunque _MEIPASS no exista en los stubs, en runtime PyInstaller lo crea
#     base_path = getattr(sys, '_MEIPASS', os.path.abspath('.'))
# else:
#     base_path = os.path.abspath('.')

"""
if __name__ == '__main__':
    # Lanza el thread que abrirá el navegador
    threading.Thread(target=open_browser, daemon=True).start()
    # Arranca el servidor Flask (debug=False para producción)
    app.run(host='0.0.0.0', port=8000, debug=False)
"""
# Si se utiliza un entorno virtual en desarrollo, para activarlo una vez creado:
    # Windows: venv\Scripts\activate
    # Linux/Mac: source venv/bin/activate
# Para ejecutar el script en desarrollo:# python main.py

# Para hacer un ejecutable en Windows:
    # pip install pyinstaller
    # pyinstaller --onefile --windowed --add-data "templates;templates" --add-data "README.md;." --icon=icono.ico main.py
    # Para incluir un icono (lo dejo en el repositorio) se incluye --icon=icono.ico
    # El ejecutable se generará en la carpeta dist.
# Para ejecutar el ejecutable: dist\datos_personales.exe