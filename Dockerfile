FROM python:3.11-slim

# Installer les dépendances système
RUN apt update && apt install -y \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    default-libmysqlclient-dev \
    pkg-config \
    && apt clean

# Définir le dossier de travail
WORKDIR /app

# Copier les fichiers dans le conteneur
COPY . /app/

# Mettre à jour pip
RUN pip install --upgrade pip

# Installer les paquets Python
RUN pip install -r requirements.txt

# Debug : afficher les paquets installés
RUN pip list

# Lancer le serveur Django
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
