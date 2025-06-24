# datos_personales
Esta aplicación web en Python extrae datos personales de ficheros pdf usando IA en local

# Descripción
El fichero principal es main.py, creado con Flask, que llama a index.html para subir los ficheros y dar los resultados.
La aplicación funciona con LM Studio como servidor de IA. Se ha utilizado el modelo "deepseek-r1-0528-qwen3-8b@q8_0". Si se quiere usar otro es recomendable cambiarlo en la variable model de main.py

El repositorio incluye un modelo de instancia con la que se ha configurado la aplicación. Si se utiliza otro tipo de formulario o modelo deberá comprobarse y, en su caso, ir adaptando el prompt en main.py.

Desde la página web se pueden subir uno o varios archivos pdf. Una vez que la aplicación da los resultados, aparecen unos botones para exportarlos a pdf, csv o docx.