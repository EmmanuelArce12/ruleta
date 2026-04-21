import random
import string
import sqlite3

def seleccionar_premio(estacion_id):
    """Selecciona un premio de la base de datos de esa estación específica."""
    conn = sqlite3.connect('estacion.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM premios WHERE peso > 0 AND estacion_id = ?", (estacion_id,))
    premios_db = cursor.fetchall()
    conn.close()

    # Fallback YPF style
    if not premios_db:
        return {"nombre": "Volvé a intentarlo en tu próxima carga", "sector": "NINGUNO"}

    nombres = [p["nombre"] for p in premios_db]
    pesos = [p["peso"] for p in premios_db]
    
    seleccionado = random.choices(nombres, weights=pesos, k=1)[0]
    detalles = next(p for p in premios_db if p["nombre"] == seleccionado)
    
    return dict(detalles) 

def generar_token(longitud=6):
    caracteres = string.ascii_uppercase + string.digits
    return ''.join(random.choice(caracteres) for _ in range(longitud))