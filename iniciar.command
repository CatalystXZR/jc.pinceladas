#!/bin/bash

cd "$(dirname "$0")"

echo "Iniciando plataforma de cursos..."
echo ""

if ! command -v python3 &> /dev/null; then
    echo "Python3 no esta instalado."
    echo "Descargalo desde: https://www.python.org/downloads/"
    echo ""
    read -p "Presiona Enter para cerrar..."
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Instalando dependencias..."
pip install -r requirements.txt -q

echo ""
echo "Configuracion recomendada para local:"
echo "- APP_ENV=development"
echo "- PLATFORM_URL=http://localhost:5000"
echo ""
echo "Abriendo servidor en http://localhost:5000"
echo ""

python3 main.py
