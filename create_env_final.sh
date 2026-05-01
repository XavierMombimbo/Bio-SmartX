#!/bin/bash
echo "=== CRÉATION DÉFINITIVE ENVIRONNEMENT ==="

# Nettoyage
echo "1. Nettoyage..."
deactivate 2>/dev/null
rm -rf env_linux

# Python 3.11 path
PY311="/cygdrive/c/Users/Dell Latitude 5400/AppData/Local/Programs/Python/Python311/python.exe"

echo "2. Vérification Python 3.11..."
"$PY311" --version

echo "3. Création environnement..."
"$PY311" -m virtualenv env_linux

echo "4. Correction des chemins..."
if [ -d "env_linux" ]; then
    # Corrige activate
    if [ -f "env_linux/Scripts/activate" ]; then
        sed -i 's|\\\\|/|g' env_linux/Scripts/activate 2>/dev/null
        sed -i 's|\\|/|g' env_linux/Scripts/activate 2>/dev/null
        sed -i 's|\r$||' env_linux/Scripts/activate 2>/dev/null
        echo "✅ activate corrigé"
    fi
    
    # Corrige tous les scripts
    find env_linux/Scripts -type f -exec sed -i 's|\r$||' {} \; 2>/dev/null
fi

echo "5. Activation..."
if [ -f "env_linux/Scripts/activate" ]; then
    source env_linux/Scripts/activate
    echo "Python: $(python --version 2>&1)"
    echo "Chemin: $(which python 2>/dev/null || echo 'Non trouvé')"
else
    echo "❌ Fichier activate manquant"
    # Créez-le manuellement
    cat > env_linux/Scripts/activate << 'ACTIVATE'
#!/bin/bash
export VIRTUAL_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$VIRTUAL_ENV/Scripts:$PATH"
unset PYTHONHOME
PS1="(env_linux) $PS1"
ACTIVATE
    chmod +x env_linux/Scripts/activate
    source env_linux/Scripts/activate
fi

echo "6. Test Python..."
env_linux/Scripts/python.exe --version 2>/dev/null || \
env_linux/Scripts/python --version 2>/dev/null || \
echo "⚠ Impossible d'exécuter Python depuis l'environnement"

echo "=== FIN ==="
