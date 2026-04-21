from flask import Flask, render_template, request, jsonify, redirect, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
import smtplib
import random
import string
import openpyxl
import os
from datetime import date
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
# Variables leídas desde Render
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'super_clave_secreta_ge')
MI_PASSWORD = os.environ.get('PASSWORD_CORREO')
SUPERADMIN_PASS = os.environ.get('CLAVE_SUPERADMIN')
DATABASE_URL = os.environ.get('DATABASE_URL')

# Configuraciones fijas
MI_CORREO = "echeverriaehijosaforadores@gmail.com"
SUPERADMIN_USER = "dueño"

def get_db():
    return psycopg2.connect(DATABASE_URL)

def enviar_email(destinatario, nombre_cliente, premio, token):
    try:
        msg = MIMEMultipart()
        msg['From'] = MI_CORREO
        msg['To'] = destinatario
        msg['Subject'] = f"¡Felicitaciones {nombre_cliente}! Ganaste un premio en Grupo GE"
        cuerpo = f"Hola {nombre_cliente},\n\n¡Gracias por participar!\nHas ganado: {premio}\nTu código de canje es: {token}\n\n¡Te esperamos!"
        msg.attach(MIMEText(cuerpo, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        # Limpieza por si quedó algún espacio en la variable de entorno
        clave_limpia = MI_PASSWORD.replace(" ", "") if MI_PASSWORD else ""
        server.login(MI_CORREO, clave_limpia)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error correo: {e}")
        return False

def generar_token():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# --- EL CEREBRO DE LA RULETA ---
def seleccionar_premio_inteligente(estacion_id):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    c.execute("SELECT * FROM premios WHERE estacion_id = %s", (estacion_id,))
    premios_db = c.fetchall()
    
    hoy = date.today().strftime('%Y-%m-%d')
    c.execute("SELECT premio, COUNT(*) as cant FROM canjes WHERE estacion_id = %s AND DATE(fecha) = %s GROUP BY premio", (estacion_id, hoy))
    canjes_hoy = c.fetchall()
    entregados_hoy = {row['premio']: row['cant'] for row in canjes_hoy}
    
    premios_validos = []
    pesos = []
    
    for p in premios_db:
        limite = p['limite_diario'] if p['limite_diario'] else 0
        entregados = entregados_hoy.get(p['nombre'], 0)
        
        if limite > 0 and entregados >= limite:
            continue
            
        premios_validos.append(p)
        pesos.append(p['peso'])
        
    conn.close()
    
    if not premios_validos:
        return {"nombre": "Sigue intentando", "sector": "NINGUNO", "imagen_url": ""}
        
    premio_ganador = random.choices(premios_validos, weights=pesos, k=1)[0]
    return dict(premio_ganador)

def init_db():
    try:
        print("=========================================")
        print("⏳ INTENTANDO CONECTAR A LA BASE DE DATOS...")
        url_segura = f"{str(DATABASE_URL)[:20]}..." if DATABASE_URL else "NINGUNA (Revisar Render)"
        print(f"URL detectada: {url_segura}") 
        print("=========================================")
        
        conn = get_db()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS estaciones (id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, admin_user TEXT UNIQUE NOT NULL, admin_pass TEXT NOT NULL, ruleta_user TEXT UNIQUE, ruleta_pass TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS canjes (id SERIAL PRIMARY KEY, estacion_id INTEGER, nombre TEXT, dni TEXT, email TEXT, telefono TEXT, premio TEXT, token TEXT, sector TEXT, estado TEXT DEFAULT 'PENDIENTE', vendedor_canje TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(estacion_id) REFERENCES estaciones(id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS premios (id SERIAL PRIMARY KEY, estacion_id INTEGER, nombre TEXT NOT NULL, tipo TEXT NOT NULL, dificultad TEXT NOT NULL, peso INTEGER NOT NULL, sector TEXT NOT NULL, imagen_url TEXT, limite_diario INTEGER DEFAULT 0, FOREIGN KEY(estacion_id) REFERENCES estaciones(id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS vendedores (id SERIAL PRIMARY KEY, estacion_id INTEGER, nombre TEXT NOT NULL, pin TEXT NOT NULL, sector TEXT NOT NULL, FOREIGN KEY(estacion_id) REFERENCES estaciones(id))''')
        conn.commit()
        conn.close()
        
        print("✅ BASE DE DATOS CONECTADA Y LISTA")
    except Exception as e:
        print("=========================================")
        print("🔥 ERROR FATAL AL INICIAR LA BASE DE DATOS 🔥")
        print(f"MOTIVO EXACTO: {e}")
        print("Revisa tus variables de entorno en Render.")
        print("=========================================")

init_db()

# ==========================================
# 1. SUPER ADMIN
# ==========================================
@app.route('/login_superadmin', methods=['GET', 'POST'])
def login_superadmin():
    error = None
    if request.method == 'POST':
        if request.form['usuario'] == SUPERADMIN_USER and request.form['password'] == SUPERADMIN_PASS:
            session['super_auth'] = True
            return redirect('/superadmin')
        error = "Credenciales incorrectas"
    return render_template('login_superadmin.html', error=error)

@app.route('/logout_superadmin')
def logout_superadmin():
    session.pop('super_auth', None)
    return redirect('/login_superadmin')

@app.route('/superadmin')
def superadmin():
    if not session.get('super_auth'): return redirect('/login_superadmin')
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM estaciones ORDER BY id DESC")
    estaciones = c.fetchall()
    conn.close()
    return render_template('superadmin.html', estaciones=estaciones)

@app.route('/superadmin/crear_estacion', methods=['POST'])
def crear_estacion():
    if not session.get('super_auth'): return redirect('/login_superadmin')
    h = generate_password_hash(request.form['password'])
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO estaciones (nombre, admin_user, admin_pass) VALUES (%s, %s, %s)', (request.form['nombre'], request.form['usuario'].lower().replace(" ", ""), h))
        conn.commit()
    except Exception as e: 
        print("Error al crear:", e)
        conn.rollback()
    finally:
        conn.close()
    return redirect('/superadmin')

@app.route('/superadmin/borrar_estacion/<int:id>', methods=['POST'])
def borrar_estacion(id):
    if not session.get('super_auth'): return redirect('/login_superadmin')
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM premios WHERE estacion_id = %s', (id,))
    c.execute('DELETE FROM vendedores WHERE estacion_id = %s', (id,))
    c.execute('DELETE FROM canjes WHERE estacion_id = %s', (id,))
    c.execute('DELETE FROM estaciones WHERE id = %s', (id,))
    conn.commit(); conn.close()
    return redirect('/superadmin')

@app.route('/superadmin/blanquear_clave/<int:id>', methods=['POST'])
def blanquear_clave(id):
    if not session.get('super_auth'): return redirect('/login_superadmin')
    h = generate_password_hash(request.form['nueva_clave'])
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE estaciones SET admin_pass = %s WHERE id = %s', (h, id))
    conn.commit(); conn.close()
    return redirect('/superadmin')

# ==========================================
# 2. ADMIN DE ESTACIÓN
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login_admin():
    error = None
    if request.method == 'POST':
        conn = get_db()
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("SELECT * FROM estaciones WHERE admin_user = %s", (request.form['usuario'],))
        estacion = c.fetchone()
        conn.close()
        if estacion and check_password_hash(estacion['admin_pass'], request.form['password']):
            session['estacion_id'] = estacion['id']
            session['estacion_nombre'] = estacion['nombre']
            return redirect('/admin')
        error = "Datos incorrectos."
    return render_template('login_admin.html', error=error)

@app.route('/logout_admin')
def logout_admin(): session.clear(); return redirect('/login')

@app.route('/admin')
def panel_admin():
    if 'estacion_id' not in session: return redirect('/login')
    eid = session['estacion_id']
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    c.execute("SELECT ruleta_user, ruleta_pass FROM estaciones WHERE id = %s", (eid,))
    estacion = c.fetchone()
    
    c.execute("SELECT * FROM canjes WHERE estacion_id = %s ORDER BY fecha DESC", (eid,))
    clientes = c.fetchall()
    
    c.execute("SELECT * FROM vendedores WHERE estacion_id = %s", (eid,))
    vendedores = c.fetchall()
    
    hoy = date.today().strftime('%Y-%m-%d')
    c.execute("SELECT premio, COUNT(*) as cant FROM canjes WHERE estacion_id = %s AND DATE(fecha) = %s GROUP BY premio", (eid, hoy))
    canjes_hoy = c.fetchall()
    entregados_hoy = {row['premio']: row['cant'] for row in canjes_hoy}
    
    c.execute("SELECT * FROM premios WHERE estacion_id = %s", (eid,))
    premios_db = c.fetchall()
    
    total_peso_activo = 0
    for p in premios_db:
        limite = p['limite_diario'] if p['limite_diario'] else 0
        entregados = entregados_hoy.get(p['nombre'], 0)
        if limite == 0 or entregados < limite:
            total_peso_activo += p['peso']
    
    premios = []
    for p in premios_db:
        p_dict = dict(p)
        limite = p['limite_diario'] if p['limite_diario'] else 0
        entregados = entregados_hoy.get(p['nombre'], 0)
        
        p_dict['entregados_hoy'] = entregados
        
        if limite > 0 and entregados >= limite:
            p_dict['probabilidad_porcentaje'] = 0.00
            p_dict['estado'] = "AGOTADO HOY"
        else:
            p_dict['probabilidad_porcentaje'] = round((p['peso'] / total_peso_activo * 100), 2) if total_peso_activo > 0 else 0
            p_dict['estado'] = "ACTIVO"
            
        premios.append(p_dict)
        
    conn.close()
    return render_template('administrador.html', clientes=clientes, premios=premios, vendedores=vendedores, estacion=estacion, nombre_estacion=session['estacion_nombre'])

@app.route('/admin/configurar_ruleta', methods=['POST'])
def configurar_ruleta():
    if 'estacion_id' not in session: return redirect('/login')
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE estaciones SET ruleta_user = %s, ruleta_pass = %s WHERE id = %s', (request.form['ruleta_user'].lower().replace(" ",""), request.form['ruleta_pass'], session['estacion_id']))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/borrar_ruleta', methods=['POST'])
def borrar_ruleta():
    if 'estacion_id' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE estaciones SET ruleta_user = NULL, ruleta_pass = NULL WHERE id = %s', (session['estacion_id'],))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/blanquear_ruleta', methods=['POST'])
def blanquear_ruleta():
    if 'estacion_id' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE estaciones SET ruleta_pass = %s WHERE id = %s', (request.form['nueva_clave'], session['estacion_id']))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/agregar_premio', methods=['POST'])
def agregar_premio():
    if 'estacion_id' not in session: return redirect('/login')
    pesos = {"Consuelo": 1000, "Frecuente": 100, "Normal": 20, "Raro": 5, "Imposible": 1}
    peso = pesos.get(request.form['dificultad'], 10)
    
    limite = request.form.get('limite_diario', 0)
    if not limite: limite = 0
    
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO premios (estacion_id, nombre, tipo, dificultad, peso, sector, imagen_url, limite_diario) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', 
              (session['estacion_id'], request.form['nombre'], "General", request.form['dificultad'], peso, request.form['sector'], request.form['imagen_url'], int(limite)))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/borrar_premio/<int:id>', methods=['POST'])
def borrar_premio(id):
    if 'estacion_id' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM premios WHERE id = %s AND estacion_id = %s', (id, session['estacion_id']))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/agregar_vendedor', methods=['POST'])
def agregar_vendedor():
    if 'estacion_id' not in session: return redirect('/login')
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO vendedores (estacion_id, nombre, pin, sector) VALUES (%s, %s, %s, %s)', (session['estacion_id'], request.form['nombre'], request.form['pin'], request.form['sector']))
    conn.commit(); conn.close()
    return redirect('/admin')

@app.route('/admin/exportar_excel')
def exportar_excel():
    if 'estacion_id' not in session: return redirect('/login')
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT fecha, nombre, dni, email, telefono, premio, token, estado, vendedor_canje FROM canjes WHERE estacion_id = %s ORDER BY fecha DESC", (session['estacion_id'],))
    canjes = c.fetchall()
    conn.close()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Historial Clientes"
    ws.append(['Fecha', 'Cliente', 'DNI', 'Email', 'Telefono', 'Premio Ganado', 'Token', 'Estado', 'Entregado Por'])
    
    for canje in canjes:
        ws.append([str(canje['fecha'])[:16], canje['nombre'], canje['dni'], canje['email'], canje['telefono'], canje['premio'], canje['token'], canje['estado'], canje['vendedor_canje']])
    
    salida = BytesIO()
    wb.save(salida)
    salida.seek(0)
    
    return Response(salida.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition":"attachment;filename=historial_clientes_ge.xlsx"})

# ==========================================
# 3. RULETA
# ==========================================
@app.route('/iniciar_ruleta', methods=['GET', 'POST'])
def iniciar_ruleta():
    error = None
    if request.method == 'POST':
        conn = get_db()
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("SELECT * FROM estaciones WHERE ruleta_user = %s AND ruleta_pass = %s", (request.form['usuario'], request.form['password']))
        est = c.fetchone()
        conn.close()
        if est:
            session['ruleta_auth_id'] = est['id']
            session['ruleta_auth_nombre'] = est['nombre']
            return redirect('/ruleta')
        error = "Credenciales incorrectas."
    return render_template('login_ruleta.html', error=error)

@app.route('/ruleta')
def ver_ruleta():
    if 'ruleta_auth_id' not in session: return redirect('/iniciar_ruleta')
    return render_template('index.html', estacion_id=session['ruleta_auth_id'], nombre_estacion=session['ruleta_auth_nombre'])

@app.route('/api/premios/<int:estacion_id>')
def api_premios(estacion_id):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT nombre, imagen_url FROM premios WHERE estacion_id = %s AND (limite_diario = 0 OR limite_diario IS NULL OR nombre NOT IN (SELECT premio FROM canjes WHERE estacion_id = %s AND DATE(fecha) = CURRENT_DATE GROUP BY premio HAVING COUNT(*) >= premios.limite_diario))", (estacion_id, estacion_id))
    premios = c.fetchall()
    conn.close()
    if not premios: return jsonify([{"nombre": "Sigue intentando"}, {"nombre": "Gira de nuevo"}])
    return jsonify([dict(p) for p in premios])

@app.route('/girar/<int:estacion_id>', methods=['POST'])
def girar(estacion_id): 
    return jsonify(seleccionar_premio_inteligente(estacion_id))

@app.route('/registrar/<int:estacion_id>', methods=['POST'])
def registrar(estacion_id):
    d = request.json; t = generar_token()
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO canjes (estacion_id, nombre, dni, email, telefono, premio, token, sector) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)', (estacion_id, d['nombre'], d['dni'], d['email'], d['telefono'], d['premio'], t, d['sector']))
    conn.commit(); conn.close()
    
    if d['sector'] != 'NINGUNO': enviar_email(d['email'], d['nombre'], d['premio'], t)
    return jsonify({"status": "ok", "token": t})

# ==========================================
# 4. TERMINAL
# ==========================================
@app.route('/iniciar_terminal', methods=['GET', 'POST'])
def iniciar_terminal():
    error = None
    if request.method == 'POST':
        conn = get_db()
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute("SELECT * FROM estaciones WHERE ruleta_user = %s AND ruleta_pass = %s", (request.form['usuario'], request.form['password']))
        est = c.fetchone()
        conn.close()
        if est:
            session['terminal_auth_id'] = est['id']
            session['terminal_auth_nombre'] = est['nombre']
            return redirect('/terminal_canje')
        error = "Credenciales incorrectas."
    return render_template('login_terminal.html', error=error)

@app.route('/terminal_canje')
def terminal_canje():
    if 'terminal_auth_id' not in session: return redirect('/iniciar_terminal')
    return render_template('terminal.html', estacion_id=session['terminal_auth_id'], nombre_estacion=session['terminal_auth_nombre'])

@app.route('/logout_terminal')
def logout_terminal():
    session.pop('terminal_auth_id', None)
    session.pop('terminal_auth_nombre', None)
    return redirect('/iniciar_terminal')

@app.route('/procesar_canje/<int:estacion_id>', methods=['POST'])
def procesar_canje(estacion_id):
    token = request.json.get('token', '').upper()
    pin = request.json.get('pin', '')
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    c.execute("SELECT * FROM vendedores WHERE pin = %s AND estacion_id = %s", (pin, estacion_id))
    v = c.fetchone()
    if not v: return jsonify({"status": "error", "mensaje": "PIN incorrecto."})
    
    c.execute("SELECT * FROM canjes WHERE token = %s AND estacion_id = %s", (token, estacion_id))
    canje = c.fetchone()
    
    if not canje: return jsonify({"status": "error", "mensaje": "Código inválido."})
    if canje['estado'] == 'CANJEADO': return jsonify({"status": "error", "mensaje": "Ya canjeado."})
    
    c.execute("UPDATE canjes SET estado = 'CANJEADO', vendedor_canje = %s WHERE token = %s", (v['nombre'], token))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "mensaje": "Canje exitoso", "premio": canje['premio'], "cliente": canje['nombre']})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
