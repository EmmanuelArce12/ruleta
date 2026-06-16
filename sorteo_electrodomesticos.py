from flask import Flask, render_template, request, jsonify, redirect, session, Response, url_for
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import quote_plus
import os
import threading
import time
import json

import openpyxl
import psycopg2
import psycopg2.extras

try:
    import qrcode
except ImportError:
    qrcode = None

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SORTEO_SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY', 'clave_sorteo_electrodomesticos')
DATABASE_URL = os.environ.get('DATABASE_URL')
FACTURACION_DATABASE_URL = os.environ.get('FACTURACION_DATABASE_URL') or DATABASE_URL
FACTURACION_SQL = os.environ.get('FACTURACION_SQL')
PUBLIC_BASE_URL = os.environ.get('SORTEO_PUBLIC_BASE_URL', '').rstrip('/')
SYNC_INTERVAL_MINUTES = int(os.environ.get('SORTEO_SYNC_INTERVAL_MINUTES', '240'))
SORTEO_BASE_PATH = os.environ.get('SORTEO_BASE_PATH', '/sorteo').rstrip('/')


def get_db():
    return psycopg2.connect(DATABASE_URL)


def get_facturacion_db():
    return psycopg2.connect(FACTURACION_DATABASE_URL)


def init_db():
    conn = get_db()
    conn.autocommit = True
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sorteo_config (
            estacion_id INTEGER PRIMARY KEY REFERENCES estaciones(id) ON DELETE CASCADE,
            minimo_litros NUMERIC(10, 3) DEFAULT 0,
            intervalo_horas INTEGER DEFAULT 4,
            activo BOOLEAN DEFAULT TRUE,
            detenido BOOLEAN DEFAULT FALSE,
            ultima_consulta TIMESTAMP,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS sorteo_participantes (
            id SERIAL PRIMARY KEY,
            estacion_id INTEGER REFERENCES estaciones(id) ON DELETE CASCADE,
            ticket_hora TIMESTAMP NOT NULL,
            numero_factura TEXT NOT NULL,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            dni TEXT,
            telefono TEXT NOT NULL,
            email TEXT NOT NULL,
            estado TEXT DEFAULT 'PENDIENTE',
            combustible TEXT,
            litros NUMERIC(10, 3),
            pago_app_ypf BOOLEAN,
            detalle_validacion TEXT,
            consulta_at TIMESTAMP,
            conteo_id INTEGER,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS sorteo_conteos (
            id SERIAL PRIMARY KEY,
            estacion_id INTEGER REFERENCES estaciones(id) ON DELETE CASCADE,
            iniciado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total INTEGER DEFAULT 0,
            aprobados INTEGER DEFAULT 0,
            denegados INTEGER DEFAULT 0,
            pendientes INTEGER DEFAULT 0,
            snapshot_json TEXT
        )
    ''')
    c.execute('''
        CREATE INDEX IF NOT EXISTS idx_sorteo_participantes_estacion_activo
        ON sorteo_participantes(estacion_id, conteo_id, creado_en DESC)
    ''')
    c.execute('DROP INDEX IF EXISTS idx_sorteo_participantes_factura_estacion')
    c.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sorteo_participantes_factura_estacion_activa
        ON sorteo_participantes(estacion_id, numero_factura)
        WHERE conteo_id IS NULL
    ''')
    conn.close()


def ensure_config(estacion_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO sorteo_config (estacion_id) VALUES (%s) ON CONFLICT (estacion_id) DO NOTHING', (estacion_id,))
    conn.commit()
    conn.close()


def admin_required():
    return 'sorteo_estacion_id' in session


def sorteo_path(path=''):
    if not path.startswith('/'):
        path = '/' + path
    return f'{SORTEO_BASE_PATH}{path}' if SORTEO_BASE_PATH else path

def public_url(estacion_id):
    path = sorteo_path(f'/{estacion_id}')
    if PUBLIC_BASE_URL:
        return f'{PUBLIC_BASE_URL}{path}'
    return request.host_url.rstrip('/') + path


def qr_data_url(text):
    if qrcode is None:
        return None
    img = qrcode.make(text)
    salida = BytesIO()
    img.save(salida, format='PNG')
    import base64
    return 'data:image/png;base64,' + base64.b64encode(salida.getvalue()).decode('ascii')


def parse_ticket_time(fecha, hora):
    return datetime.strptime(f'{fecha} {hora}', '%Y-%m-%d %H:%M:%S')


def consultar_facturacion(estacion_id, ticket_hora, numero_factura):
    if not FACTURACION_SQL:
        return None, 'Falta configurar FACTURACION_SQL en el entorno.'

    conn = get_facturacion_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    params = {
        'estacion_id': estacion_id,
        'ticket_hora': ticket_hora,
        'numero_factura': numero_factura,
    }
    c.execute(FACTURACION_SQL, params)
    row = c.fetchone()
    conn.close()

    if not row:
        return None, 'No se encontro una factura que coincida con numero y hora exacta.'
    return dict(row), None


def validar_pendientes(estacion_id=None):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if estacion_id:
        c.execute('''
            SELECT p.*, cfg.minimo_litros
            FROM sorteo_participantes p
            JOIN sorteo_config cfg ON cfg.estacion_id = p.estacion_id
            WHERE p.estado = 'PENDIENTE' AND p.conteo_id IS NULL AND p.estacion_id = %s
            ORDER BY p.creado_en ASC
        ''', (estacion_id,))
    else:
        c.execute('''
            SELECT p.*, cfg.minimo_litros
            FROM sorteo_participantes p
            JOIN sorteo_config cfg ON cfg.estacion_id = p.estacion_id
            WHERE p.estado = 'PENDIENTE' AND p.conteo_id IS NULL
            ORDER BY p.creado_en ASC
        ''')
    pendientes = c.fetchall()

    for p in pendientes:
        factura, error = consultar_facturacion(p['estacion_id'], p['ticket_hora'], p['numero_factura'])
        if error:
            c.execute('''
                UPDATE sorteo_participantes
                SET detalle_validacion = %s, consulta_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (error, p['id']))
            continue

        litros = factura.get('litros') or factura.get('cantidad_litros') or 0
        combustible = factura.get('combustible') or factura.get('producto')
        pago_app_ypf = factura.get('pago_app_ypf')
        minimo = p['minimo_litros'] or 0
        estado = 'APROBADO' if float(litros or 0) >= float(minimo) else 'DENEGADO'
        detalle = 'Validado correctamente.' if estado == 'APROBADO' else f'Litros insuficientes: {litros} de minimo {minimo}.'

        c.execute('''
            UPDATE sorteo_participantes
            SET estado = %s, combustible = %s, litros = %s, pago_app_ypf = %s,
                detalle_validacion = %s, consulta_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (estado, combustible, litros, pago_app_ypf, detalle, p['id']))

    if estacion_id:
        c.execute('UPDATE sorteo_config SET ultima_consulta = CURRENT_TIMESTAMP, actualizado_en = CURRENT_TIMESTAMP WHERE estacion_id = %s', (estacion_id,))
    else:
        c.execute('UPDATE sorteo_config SET ultima_consulta = CURRENT_TIMESTAMP, actualizado_en = CURRENT_TIMESTAMP')
    conn.commit()
    conn.close()
    return len(pendientes)


def scheduler_loop():
    while True:
        time.sleep(60)
        try:
            conn = get_db()
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute('''
                SELECT estacion_id
                FROM sorteo_config
                WHERE activo = TRUE
                  AND detenido = FALSE
                  AND (
                    ultima_consulta IS NULL OR
                    ultima_consulta <= CURRENT_TIMESTAMP - (intervalo_horas || ' hours')::interval
                  )
            ''')
            estaciones = c.fetchall()
            conn.close()
            for est in estaciones:
                validar_pendientes(est['estacion_id'])
        except Exception as exc:
            print('Error en scheduler sorteo:', exc)


@app.route('/')
@app.route('/sorteo')
def root():
    return redirect(sorteo_path('/admin'))


@app.route('/admin/login', methods=['GET', 'POST'])
@app.route('/sorteo/admin/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        usuario = request.form['usuario'].lower().strip()
        password = request.form['password']
        conn = get_db()
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        c.execute('SELECT * FROM estaciones WHERE admin_user = %s', (usuario,))
        estacion = c.fetchone()
        conn.close()
        if estacion and check_password_hash(estacion['admin_pass'], password):
            session['sorteo_estacion_id'] = estacion['id']
            session['sorteo_estacion_nombre'] = estacion['nombre']
            ensure_config(estacion['id'])
            return redirect(sorteo_path('/admin'))
        error = 'Credenciales incorrectas.'
    return render_template('sorteo_login.html', error=error)


@app.route('/admin/logout')
@app.route('/sorteo/admin/logout')
def logout():
    session.clear()
    return redirect(sorteo_path('/admin/login'))


@app.route('/admin')
@app.route('/sorteo/admin')
def admin():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    eid = session['sorteo_estacion_id']
    ensure_config(eid)
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT * FROM sorteo_config WHERE estacion_id = %s', (eid,))
    config = c.fetchone()
    c.execute('SELECT * FROM sorteo_participantes WHERE estacion_id = %s AND conteo_id IS NULL ORDER BY creado_en DESC', (eid,))
    participantes = c.fetchall()
    c.execute('SELECT * FROM sorteo_conteos WHERE estacion_id = %s ORDER BY iniciado_en DESC LIMIT 10', (eid,))
    conteos = c.fetchall()
    conn.close()
    url = public_url(eid)
    return render_template('sorteo_admin.html', nombre_estacion=session['sorteo_estacion_nombre'], config=config,
                           participantes=participantes, conteos=conteos, public_url=url, qr=qr_data_url(url),
                           facturacion_configurada=bool(FACTURACION_SQL), base_path=SORTEO_BASE_PATH)


@app.route('/admin/config', methods=['POST'])
@app.route('/sorteo/admin/config', methods=['POST'])
def configurar():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    eid = session['sorteo_estacion_id']
    minimo_litros = request.form.get('minimo_litros') or 0
    intervalo_horas = request.form.get('intervalo_horas') or 4
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE sorteo_config
        SET minimo_litros = %s, intervalo_horas = %s, actualizado_en = CURRENT_TIMESTAMP
        WHERE estacion_id = %s
    ''', (minimo_litros, intervalo_horas, eid))
    conn.commit()
    conn.close()
    return redirect(sorteo_path('/admin'))


@app.route('/admin/forzar-consulta', methods=['POST'])
@app.route('/sorteo/admin/forzar-consulta', methods=['POST'])
def forzar_consulta():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    validar_pendientes(session['sorteo_estacion_id'])
    return redirect(sorteo_path('/admin'))


@app.route('/admin/detener', methods=['POST'])
@app.route('/sorteo/admin/detener', methods=['POST'])
def detener():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE sorteo_config SET detenido = TRUE, actualizado_en = CURRENT_TIMESTAMP WHERE estacion_id = %s', (session['sorteo_estacion_id'],))
    conn.commit()
    conn.close()
    return redirect(sorteo_path('/admin'))


@app.route('/admin/reanudar', methods=['POST'])
@app.route('/sorteo/admin/reanudar', methods=['POST'])
def reanudar():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE sorteo_config SET detenido = FALSE, actualizado_en = CURRENT_TIMESTAMP WHERE estacion_id = %s', (session['sorteo_estacion_id'],))
    conn.commit()
    conn.close()
    return redirect(sorteo_path('/admin'))


@app.route('/admin/iniciar-conteo', methods=['POST'])
@app.route('/sorteo/admin/iniciar-conteo', methods=['POST'])
def iniciar_conteo():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    eid = session['sorteo_estacion_id']
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT * FROM sorteo_participantes WHERE estacion_id = %s AND conteo_id IS NULL ORDER BY creado_en ASC', (eid,))
    participantes = c.fetchall()
    total = len(participantes)
    aprobados = sum(1 for p in participantes if p['estado'] == 'APROBADO')
    denegados = sum(1 for p in participantes if p['estado'] == 'DENEGADO')
    pendientes = sum(1 for p in participantes if p['estado'] == 'PENDIENTE')
    snapshot = json.dumps([dict(p) for p in participantes], default=str, ensure_ascii=False)
    c.execute('''
        INSERT INTO sorteo_conteos (estacion_id, total, aprobados, denegados, pendientes, snapshot_json)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    ''', (eid, total, aprobados, denegados, pendientes, snapshot))
    conteo_id = c.fetchone()['id']
    c.execute('UPDATE sorteo_participantes SET conteo_id = %s WHERE estacion_id = %s AND conteo_id IS NULL', (conteo_id, eid))
    conn.commit()
    conn.close()
    return redirect(sorteo_path('/admin'))


@app.route('/admin/exportar-excel')
@app.route('/sorteo/admin/exportar-excel')
def exportar_excel():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    eid = session['sorteo_estacion_id']
    incluir_archivados = request.args.get('todo') == '1'
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if incluir_archivados:
        c.execute('SELECT * FROM sorteo_participantes WHERE estacion_id = %s ORDER BY creado_en DESC', (eid,))
    else:
        c.execute('SELECT * FROM sorteo_participantes WHERE estacion_id = %s AND conteo_id IS NULL ORDER BY creado_en DESC', (eid,))
    rows = c.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sorteo Electrodomesticos'
    ws.append(['Registro', 'Estado', 'Hora ticket', 'Registro interno', 'Combustible', 'Litros', 'Pago App YPF', 'Nombre', 'Apellido', 'DNI', 'Telefono', 'Email', 'Detalle', 'Consultado', 'Conteo'])
    for r in rows:
        ws.append([str(r['creado_en'])[:19], r['estado'], str(r['ticket_hora'])[:19], r['numero_factura'], r['combustible'], r['litros'], r['pago_app_ypf'], r['nombre'], r['apellido'], r['dni'], r['telefono'], r['email'], r['detalle_validacion'], str(r['consulta_at'])[:19] if r['consulta_at'] else '', r['conteo_id']])
    salida = BytesIO()
    wb.save(salida)
    salida.seek(0)
    return Response(salida.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment;filename=sorteo_electrodomesticos.xlsx'})


@app.route('/<int:estacion_id>', methods=['GET', 'POST'])
@app.route('/sorteo/<int:estacion_id>', methods=['GET', 'POST'])
@app.route('/participar/<int:estacion_id>', methods=['GET', 'POST'])
def cliente_sorteo(estacion_id):
    ensure_config(estacion_id)
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT nombre FROM estaciones WHERE id = %s', (estacion_id,))
    estacion = c.fetchone()
    c.execute('SELECT detenido FROM sorteo_config WHERE estacion_id = %s', (estacion_id,))
    config = c.fetchone()
    mensaje = None
    error = None

    if not estacion:
        conn.close()
        return 'Estacion no encontrada', 404

    if request.method == 'POST':
        if config and config['detenido']:
            error = 'El sorteo se encuentra cerrado.'
        else:
            try:
                ticket_hora = parse_ticket_time(request.form['fecha_ticket'], request.form['hora_ticket'])
                registro_interno = f'AUTO-{estacion_id}-{time.time_ns()}'
                c.execute('''
                    INSERT INTO sorteo_participantes
                    (estacion_id, ticket_hora, numero_factura, nombre, apellido, dni, telefono, email)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (estacion_id, ticket_hora, registro_interno, request.form['nombre'].strip(),
                      request.form['apellido'].strip(), request.form.get('dni', '').strip(), request.form['telefono'].strip(),
                      request.form['email'].strip().lower()))
                conn.commit()
                mensaje = 'Tu cupon quedo registrado como pendiente. Cuando se valide el ticket, participas si cumple las condiciones.'
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                error = 'No pudimos registrar el cupon. Por favor intenta nuevamente.'
            except ValueError:
                error = 'La hora debe incluir segundos y tener formato HH:MM:SS.'
    conn.close()
    return render_template('sorteo_cliente.html', estacion=estacion, mensaje=mensaje, error=error, detenido=config and config['detenido'])


init_db()

if os.environ.get('SORTEO_DISABLE_SCHEDULER') != '1':
    threading.Thread(target=scheduler_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('SORTEO_PORT', '5055')))

