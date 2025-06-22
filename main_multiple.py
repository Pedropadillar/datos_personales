from flask import Flask, render_template, request, redirect, url_for, send_file, session
import openai
import fitz  # PyMuPDF
import json
import io
import csv
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import letter
from docx import Document

app = Flask(__name__, template_folder="templates")
app.secret_key = "una_clave_secreta_que_tu_quieras"  # Necesario para sesión

client = openai.OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="not-needed" 
)

def extract_text_from_file(file_bytes, mimetype):
    text = ''
    if mimetype == 'application/pdf':
        with fitz.open(stream=file_bytes, filetype='pdf') as doc:
            for page in doc:
                text += page.get_text()
    else:
        text = file_bytes.decode('utf-8', errors='replace')
    return text

def extract_personal_data(content_text):
    prompt = f"""
Extrae los siguientes datos personales del texto y responde **SOLO** con un JSON con estas claves, sin ninguna explicación ni razonamiento, sin ningún texto adicional, únicamente el JSON:
- nombre_completo
- email
- telefono
- direccion
- DNI

Si algún dato no está presente, asigna null. Donde pone DNI debes buscar CIF/NIF/NIE/Otro y devolver el número completo.

Aquí está el texto:
---
{content_text}
---
"""
    response = client.chat.completions.create(
        model="gemma-3-12b-it-qat",
        messages=[
            {"role": "system", "content": (
                "Eres un asistente que extrae datos personales de documentos. Examina detenidamente los documentos y extrae los datos solicitados de forma precisa. "
                "Responde exclusivamente con los datos solicitados, sin ninguna explicación."
            )},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
    )
    raw = response.choices[0].message.content.strip()
    print('RESPUESTA CRUDA DEL MODELO:', raw)
    # Si hay razonamiento, intenta quedarte solo con el primer bloque JSON
    if '{' in raw and '}' in raw:
        raw_json = raw[raw.find('{'):raw.rfind('}')+1]
    else:
        raw_json = raw
    try:
        data = json.loads(raw_json)
    except Exception as e:
        print('Error al parsear JSON:', e)
        data = {"nombre_completo": None, "email": None, "telefono": None, "direccion": None, "DNI": None}
    return data

@app.route('/', methods=['GET'])
def index():
    return render_template('index_multiple.html', results=None, error=None)

@app.route('/cancelar', methods=['GET'])
def cancelar():
    return render_template('index_multiple.html', results=None, error="El proceso fue cancelado.")

@app.route('/extraer-datos/', methods=['POST'])
def extraer_datos(): #extraemos los datos personales
    error = None
    results = []

    files = request.files.getlist('file')
    if not files or files[0].filename == '':
        return render_template('index_multiple.html', results=None, error="No se subió ningún archivo.")

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
                "nombre_completo": None, "email": None, "telefono": None, "direccion": None, "dni": None
            }, 'error': str(e)})

    session['results'] = results  # Guardar para exportar
    print('RESULTADOS:', results)
    return render_template('index_multiple.html', results=results, error=error)

@app.route('/exportar_csv')
def exportar_csv():
   
    results = session.get('results', [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Archivo', 'Nombre Completo', 'Email', 'Teléfono', 'Dirección', 'DNI'])
    for r in results:
        d = r['data']
        direccion = d.get('direccion')
        # Si es dict, conviértelo a string
        if isinstance(direccion, dict):
            direccion = ', '.join([f"{k}: {v}" for k, v in direccion.items()])
        writer.writerow([
            r['filename'],
            d.get('nombre_completo'), d.get('email'), d.get('telefono'),
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
            Paragraph('Nombre Completo', styleN),
            Paragraph('Email', styleN),
            Paragraph('Teléfono', styleN),
            Paragraph('Dirección', styleN),
            Paragraph('DNI', styleN)
        ]
    ]

    for r in results:
        d = r['data']
        # Dirección postal: dict => string bonito
        direccion = d.get('direccion', '') or ''
        if isinstance(direccion, dict):
            direccion = ', '.join([f"{k}: {v}" for k, v in direccion.items()])
        else:
            direccion = str(direccion)
        # Cuidado con None
        dni = d.get('DNI', '') or ''
        data.append([
            Paragraph(str(r['filename']), styleN),
            Paragraph(str(d.get('nombre_completo', '') or ''), styleN),
            Paragraph(str(d.get('email', '') or ''), styleN),
            Paragraph(str(d.get('telefono', '') or ''), styleN),
            Paragraph(direccion, styleN),
            Paragraph(dni, styleN)
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
        row_cells[1].text = str(d.get('nombre_completo'))
        row_cells[2].text = str(d.get('email'))
        row_cells[3].text = str(d.get('telefono'))
        row_cells[4].text = str(d.get('direccion'))
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
