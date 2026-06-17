from flask import Flask, render_template, request, redirect, session, Response
from werkzeug.security import check_password_hash
from datetime import datetime, date
from io import BytesIO
from decimal import Decimal
import os
import re
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
from debo import SQLSERVER_DRIVER, station_debo_ready, validate_ticket_invoice_on_date

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SORTEO_SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY', 'clave_sorteo_electrodomesticos')
DATABASE_URL = os.environ.get('DATABASE_URL')
PUBLIC_BASE_URL = os.environ.get('SORTEO_PUBLIC_BASE_URL', '').rstrip('/')
SORTEO_BASE_PATH = os.environ.get('SORTEO_BASE_PATH', '/sorteo').rstrip('/')

PROMO_COMBUSTIBLES = {'Super', 'Diesel 500', 'Infinia', 'Infinia Diesel'}
INF_INFINIA = {'Infinia', 'Infinia Diesel'}
ACTIVE_STATES = ('PENDIENTE', 'DUDOSO', 'APROBADO', 'DENEGADO')


def get_db():
    return psycopg2.connect(DATABASE_URL)


def get_sorteo_config(estacion_id):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT * FROM sorteo_config WHERE estacion_id = %s', (estacion_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_station(estacion_id):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT * FROM estaciones WHERE id = %s', (estacion_id,))
    row = c.fetchone()
    conn.close()
    return row


def init_db():
    conn = get_db()
    conn.autocommit = True
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sorteo_config (
            estacion_id INTEGER PRIMARY KEY REFERENCES estaciones(id) ON DELETE CASCADE,
            minimo_litros NUMERIC(10, 3) DEFAULT 0,
            intervalo_horas INTEGER DEFAULT 4,
            promocion_desde DATE,
            promocion_hasta DATE,
            activo BOOLEAN DEFAULT TRUE,
            detenido BOOLEAN DEFAULT FALSE,
            ultima_consulta TIMESTAMP,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute("ALTER TABLE sorteo_config ADD COLUMN IF NOT EXISTS promocion_desde DATE")
    c.execute("ALTER TABLE sorteo_config ADD COLUMN IF NOT EXISTS promocion_hasta DATE")
    c.execute('''
        CREATE TABLE IF NOT EXISTS sorteo_participantes (
            id SERIAL PRIMARY KEY,
            estacion_id INTEGER REFERENCES estaciones(id) ON DELETE CASCADE,
            ticket_fecha DATE NOT NULL,
            ticket_hora TIMESTAMP,
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
            vendedor TEXT,
            factura_real TEXT,
            chances INTEGER DEFAULT 1,
            tipo_comprobante TEXT,
            letra_fiscal TEXT,
            device_token TEXT,
            ip_registro TEXT,
            user_agent TEXT,
            sospecha_dispositivo BOOLEAN DEFAULT FALSE,
            detalle_validacion TEXT,
            consulta_at TIMESTAMP,
            conteo_id INTEGER,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS ticket_fecha DATE")
    c.execute("UPDATE sorteo_participantes SET ticket_fecha = COALESCE(ticket_fecha, ticket_hora::date) WHERE ticket_fecha IS NULL")
    c.execute("ALTER TABLE sorteo_participantes ALTER COLUMN ticket_fecha SET NOT NULL")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS ticket_hora TIMESTAMP")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS vendedor TEXT")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS factura_real TEXT")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS chances INTEGER DEFAULT 1")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS tipo_comprobante TEXT")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS letra_fiscal TEXT")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS device_token TEXT")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS ip_registro TEXT")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS user_agent TEXT")
    c.execute("ALTER TABLE sorteo_participantes ADD COLUMN IF NOT EXISTS sospecha_dispositivo BOOLEAN DEFAULT FALSE")
    c.execute('''
        CREATE TABLE IF NOT EXISTS sorteo_conteos (
            id SERIAL PRIMARY KEY,
            estacion_id INTEGER REFERENCES estaciones(id) ON DELETE CASCADE,
            iniciado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total INTEGER DEFAULT 0,
            aprobados INTEGER DEFAULT 0,
            denegados INTEGER DEFAULT 0,
            pendientes INTEGER DEFAULT 0,
            dudosos INTEGER DEFAULT 0,
            snapshot_json TEXT
        )
    ''')
    c.execute("ALTER TABLE sorteo_conteos ADD COLUMN IF NOT EXISTS dudosos INTEGER DEFAULT 0")
    c.execute('''
        CREATE INDEX IF NOT EXISTS idx_sorteo_participantes_estacion_activo
        ON sorteo_participantes(estacion_id, conteo_id, creado_en DESC)
    ''')
    c.execute('DROP INDEX IF EXISTS idx_sorteo_participantes_factura_estacion')
    c.execute('DROP INDEX IF EXISTS idx_sorteo_participantes_factura_estacion_activa')
    c.execute('DROP INDEX IF EXISTS idx_sorteo_participantes_ticket_factura_activa')
    c.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sorteo_participantes_fecha_factura_activa
        ON sorteo_participantes(estacion_id, ticket_fecha, numero_factura)
        WHERE conteo_id IS NULL
    ''')
    conn.close()


def ensure_config(estacion_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO sorteo_config (estacion_id) VALUES (%s) ON CONFLICT (estacion_id) DO NOTHING', (estacion_id,))
    c.execute('''
        UPDATE sorteo_config
        SET promocion_desde = COALESCE(promocion_desde, CURRENT_DATE),
            promocion_hasta = COALESCE(promocion_hasta, CURRENT_DATE + INTERVAL '30 days'),
            actualizado_en = CURRENT_TIMESTAMP
        WHERE estacion_id = %s
    ''', (estacion_id,))
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


def parse_ticket_date(fecha):
    return datetime.strptime(fecha, '%Y-%m-%d').date()


def normalize_invoice_number(raw_value):
    raw_value = (raw_value or '').strip()
    groups = re.findall(r'\d+', raw_value)
    if not groups:
        raise ValueError('Ingresa el numero de factura con punto de venta y numero.')
    if len(groups) >= 2:
        sucursal = int(groups[-2])
        numero = int(groups[-1])
    else:
        digits = groups[0]
        if len(digits) <= 6:
            raise ValueError('El numero de factura debe incluir punto de venta y numero.')
        sucursal = int(digits[:-6])
        numero = int(digits[-6:])
    return {
        'sucursal': sucursal,
        'numero': numero,
        'canonical': f'{sucursal}-{numero}',
    }


def decimal_to_float(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def yes_no_blank(value):
    if value is True:
        return 'Si'
    if value is False:
        return 'No'
    return ''


def split_timestamp(value):
    if not value:
        return '', ''
    text = str(value)[:19]
    parts = text.split(' ')
    if len(parts) == 2:
        return parts[0], parts[1]
    return text, ''


def compute_chances(combustible, pago_app_ypf):
    base = 2 if combustible in INF_INFINIA else 1
    return min(3, base + (1 if pago_app_ypf else 0))


def technical_validation_error(message):
    return message.startswith('Falta configurar') or message.startswith('Error consultando DEBO:')


def suspicious_device_message():
    return 'Registro marcado como dudoso: este dispositivo ya supera el limite permitido de cargas en la promocion.'


def get_client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or ''


def get_active_promo_bounds(config):
    if config and config.get('promocion_desde') and config.get('promocion_hasta'):
        return config['promocion_desde'], config['promocion_hasta']
    today = date.today()
    return today, today


def count_device_registrations(cursor, estacion_id, config, device_token, exclude_id=None):
    if not device_token:
        return 0
    promo_desde, promo_hasta = get_active_promo_bounds(config)
    sql = '''
        SELECT COUNT(*)
        FROM sorteo_participantes
        WHERE estacion_id = %s
          AND conteo_id IS NULL
          AND device_token = %s
          AND ticket_fecha >= %s
          AND ticket_fecha <= %s
    '''
    params = [estacion_id, device_token, promo_desde, promo_hasta]
    if exclude_id is not None:
        sql += ' AND id <> %s'
        params.append(exclude_id)
    cursor.execute(sql, params)
    row = cursor.fetchone()
    if isinstance(row, dict):
        return int(row.get('count', 0))
    return int(row[0]) if row else 0


def is_suspicious_device(cursor, participante, config):
    return count_device_registrations(
        cursor,
        participante['estacion_id'],
        config,
        participante.get('device_token'),
        exclude_id=participante['id'],
    ) >= 2


def consultar_facturacion(estacion_id, ticket_fecha, numero_factura):
    station = get_station(estacion_id)
    if not station_debo_ready(station):
        return None, 'Falta configurar IP, base, usuario o clave de DEBO para esta estacion.'
    try:
        factura = normalize_invoice_number(numero_factura)
    except ValueError as exc:
        return None, str(exc)
    try:
        return validate_ticket_invoice_on_date(
            station,
            datetime.combine(ticket_fecha, datetime.min.time()),
            factura['sucursal'],
            factura['numero'],
            include_remitos=bool(station.get('debo_allow_remitos')),
        )
    except Exception as exc:
        return None, f'Error consultando DEBO: {exc}'


def classify_ticket_match(factura, minimo_litros):
    promo_lineas = int(factura.get('promo_lineas') or 0)
    combustible = factura.get('combustible')
    litros = decimal_to_float(factura.get('litros'))
    if promo_lineas <= 0 or combustible not in PROMO_COMBUSTIBLES:
        return 'DENEGADO', 'La factura no corresponde a un combustible participante.'
    if litros < float(minimo_litros or 0):
        return 'DENEGADO', f'Litros insuficientes: {litros:.3f} de minimo {float(minimo_litros or 0):.3f}.'
    return 'APROBADO', 'Validado correctamente por combustible participante, aunque la factura tenga otros conceptos.'


def query_participantes(cursor, eid, archived=False):
    if archived:
        cursor.execute('SELECT * FROM sorteo_participantes WHERE estacion_id = %s ORDER BY creado_en DESC', (eid,))
    else:
        cursor.execute('SELECT * FROM sorteo_participantes WHERE estacion_id = %s AND conteo_id IS NULL ORDER BY creado_en DESC', (eid,))
    return cursor.fetchall()


def build_seller_ranking(rows):
    ranking = {}
    for row in rows:
        vendedor = (row.get('vendedor') or 'Sin vendedor').strip() or 'Sin vendedor'
        ranking[vendedor] = ranking.get(vendedor, 0) + 1
    return [
        {'vendedor': vendedor, 'facturas_aprobadas': total}
        for vendedor, total in sorted(ranking.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_admin_context(eid):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT * FROM sorteo_config WHERE estacion_id = %s', (eid,))
    config = c.fetchone()
    c.execute('SELECT * FROM estaciones WHERE id = %s', (eid,))
    station = c.fetchone()
    participantes = query_participantes(c, eid, archived=False)
    c.execute('SELECT * FROM sorteo_conteos WHERE estacion_id = %s ORDER BY iniciado_en DESC LIMIT 20', (eid,))
    conteos = c.fetchall()
    conn.close()

    aprobados = [p for p in participantes if p['estado'] == 'APROBADO']
    denegados = [p for p in participantes if p['estado'] == 'DENEGADO']
    pendientes = [p for p in participantes if p['estado'] == 'PENDIENTE']
    dudosos = [p for p in participantes if p['estado'] == 'DUDOSO']
    url = public_url(eid)

    return {
        'nombre_estacion': session['sorteo_estacion_nombre'],
        'config': config,
        'estacion': station,
        'aprobados': aprobados,
        'denegados': denegados,
        'pendientes': pendientes,
        'dudosos': dudosos,
        'conteos': conteos,
        'public_url': url,
        'qr': qr_data_url(url),
        'facturacion_configurada': station_debo_ready(station),
        'base_path': SORTEO_BASE_PATH,
        'sqlserver_driver': SQLSERVER_DRIVER,
        'seller_ranking': build_seller_ranking(aprobados),
        'totales': {
            'aprobados': len(aprobados),
            'denegados': len(denegados),
            'pendientes': len(pendientes),
            'dudosos': len(dudosos),
        },
        'split_timestamp': split_timestamp,
        'yes_no_blank': yes_no_blank,
    }


def reset_participante_validation(cursor, participante_id, estado='PENDIENTE', detalle='Esperando validacion.'):
    cursor.execute('''
        UPDATE sorteo_participantes
        SET estado = %s,
            combustible = NULL,
            litros = NULL,
            pago_app_ypf = NULL,
            vendedor = NULL,
            factura_real = NULL,
            chances = 0,
            tipo_comprobante = NULL,
            letra_fiscal = NULL,
            detalle_validacion = %s,
            consulta_at = CURRENT_TIMESTAMP
        WHERE id = %s
    ''', (estado, detalle, participante_id))


def validar_pendientes(estacion_id=None):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if estacion_id:
        c.execute('''
            SELECT p.*, cfg.minimo_litros, cfg.promocion_desde, cfg.promocion_hasta
            FROM sorteo_participantes p
            JOIN sorteo_config cfg ON cfg.estacion_id = p.estacion_id
            WHERE p.estado = 'PENDIENTE' AND p.conteo_id IS NULL AND p.estacion_id = %s
            ORDER BY p.creado_en ASC
        ''', (estacion_id,))
    else:
        c.execute('''
            SELECT p.*, cfg.minimo_litros, cfg.promocion_desde, cfg.promocion_hasta
            FROM sorteo_participantes p
            JOIN sorteo_config cfg ON cfg.estacion_id = p.estacion_id
            WHERE p.estado = 'PENDIENTE' AND p.conteo_id IS NULL
            ORDER BY p.creado_en ASC
        ''')
    pendientes = c.fetchall()

    for participante in pendientes:
        factura, error = consultar_facturacion(
            participante['estacion_id'],
            participante['ticket_fecha'],
            participante['numero_factura'],
        )
        if error:
            nuevo_estado = 'PENDIENTE' if technical_validation_error(error) else 'DENEGADO'
            reset_participante_validation(c, participante['id'], estado=nuevo_estado, detalle=error)
            continue

        estado, detalle = classify_ticket_match(factura, participante['minimo_litros'])
        combustible = factura.get('combustible')
        pago_app_ypf = bool(factura.get('pago_app_ypf'))
        chances = compute_chances(combustible, pago_app_ypf) if estado == 'APROBADO' else 0
        sospecha_dispositivo = is_suspicious_device(c, participante, participante)

        if estado == 'APROBADO' and sospecha_dispositivo:
            estado = 'DUDOSO'
            detalle = suspicious_device_message()

        c.execute('''
            UPDATE sorteo_participantes
            SET estado = %s,
                combustible = %s,
                litros = %s,
                pago_app_ypf = %s,
                vendedor = %s,
                factura_real = %s,
                chances = %s,
                tipo_comprobante = %s,
                letra_fiscal = %s,
                sospecha_dispositivo = %s,
                detalle_validacion = %s,
                consulta_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (
            estado,
            combustible,
            factura.get('litros'),
            pago_app_ypf,
            factura.get('vendedor'),
            factura.get('numero_factura'),
            chances,
            factura.get('tipo_comprobante'),
            factura.get('letra_fiscal'),
            sospecha_dispositivo,
            detalle,
            participante['id'],
        ))

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
    return render_template('sorteo_admin.html', **build_admin_context(eid))


@app.route('/admin/config', methods=['POST'])
@app.route('/sorteo/admin/config', methods=['POST'])
def configurar():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    eid = session['sorteo_estacion_id']
    minimo_litros = request.form.get('minimo_litros') or 0
    intervalo_horas = request.form.get('intervalo_horas') or 4
    promocion_desde = request.form.get('promocion_desde') or None
    promocion_hasta = request.form.get('promocion_hasta') or None
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE sorteo_config
        SET minimo_litros = %s,
            intervalo_horas = %s,
            promocion_desde = %s,
            promocion_hasta = %s,
            actualizado_en = CURRENT_TIMESTAMP
        WHERE estacion_id = %s
    ''', (minimo_litros, intervalo_horas, promocion_desde, promocion_hasta, eid))
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


def archive_current_promo(cursor, eid):
    rows = query_participantes(cursor, eid, archived=False)
    total = len(rows)
    aprobados = sum(1 for row in rows if row['estado'] == 'APROBADO')
    denegados = sum(1 for row in rows if row['estado'] == 'DENEGADO')
    pendientes = sum(1 for row in rows if row['estado'] == 'PENDIENTE')
    dudosos = sum(1 for row in rows if row['estado'] == 'DUDOSO')
    snapshot = json.dumps([dict(row) for row in rows], default=str, ensure_ascii=False)
    cursor.execute('''
        INSERT INTO sorteo_conteos (estacion_id, total, aprobados, denegados, pendientes, dudosos, snapshot_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (eid, total, aprobados, denegados, pendientes, dudosos, snapshot))
    conteo_id = cursor.fetchone()['id']
    cursor.execute('UPDATE sorteo_participantes SET conteo_id = %s WHERE estacion_id = %s AND conteo_id IS NULL', (conteo_id, eid))


@app.route('/admin/nueva-promocion', methods=['POST'])
@app.route('/sorteo/admin/nueva-promocion', methods=['POST'])
def nueva_promocion():
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    eid = session['sorteo_estacion_id']
    promocion_desde = request.form.get('promocion_desde') or None
    promocion_hasta = request.form.get('promocion_hasta') or None
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    archive_current_promo(c, eid)
    c.execute('''
        UPDATE sorteo_config
        SET promocion_desde = %s,
            promocion_hasta = %s,
            actualizado_en = CURRENT_TIMESTAMP
        WHERE estacion_id = %s
    ''', (promocion_desde, promocion_hasta, eid))
    conn.commit()
    conn.close()
    return redirect(sorteo_path('/admin'))


@app.route('/admin/dudoso/<int:participante_id>/aprobar', methods=['POST'])
@app.route('/sorteo/admin/dudoso/<int:participante_id>/aprobar', methods=['POST'])
def aprobar_dudoso(participante_id):
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE sorteo_participantes
        SET estado = 'APROBADO',
            detalle_validacion = 'Aprobado manualmente desde la bandeja de dudosos.',
            consulta_at = CURRENT_TIMESTAMP
        WHERE id = %s AND estacion_id = %s AND conteo_id IS NULL
    ''', (participante_id, session['sorteo_estacion_id']))
    conn.commit()
    conn.close()
    return redirect(sorteo_path('/admin'))


@app.route('/admin/dudoso/<int:participante_id>/denegar', methods=['POST'])
@app.route('/sorteo/admin/dudoso/<int:participante_id>/denegar', methods=['POST'])
def denegar_dudoso(participante_id):
    if not admin_required():
        return redirect(sorteo_path('/admin/login'))
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        UPDATE sorteo_participantes
        SET estado = 'DENEGADO',
            chances = 0,
            detalle_validacion = 'Denegado manualmente desde la bandeja de dudosos.',
            consulta_at = CURRENT_TIMESTAMP
        WHERE id = %s AND estacion_id = %s AND conteo_id IS NULL
    ''', (participante_id, session['sorteo_estacion_id']))
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
    estado = (request.args.get('estado') or '').upper().strip()
    ponderado = request.args.get('ponderado') == '1'

    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    rows = query_participantes(c, eid, archived=incluir_archivados)
    conn.close()

    if estado:
        rows = [row for row in rows if row['estado'] == estado]

    export_rows = []
    for row in rows:
        repeats = max(int(row.get('chances') or 1), 1) if ponderado and row['estado'] == 'APROBADO' else 1
        for idx in range(repeats):
            export_rows.append((row, idx + 1))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sorteo Electrodomesticos'
    ws.append([
        'Registro',
        'Estado',
        'Fecha ticket',
        'Factura cliente',
        'Factura DEBO',
        'Tipo',
        'Letra',
        'Vendedor',
        'Combustible',
        'Litros',
        'App YPF',
        'Chances',
        'Device token',
        'IP',
        'User agent',
        'Sospecha dispositivo',
        'Nombre',
        'Apellido',
        'DNI',
        'Telefono',
        'Email',
        'Detalle',
        'Consultado',
        'Conteo',
        'Repeticion exportada',
    ])
    for row, repetition in export_rows:
        ws.append([
            str(row['creado_en'])[:19],
            row['estado'],
            str(row['ticket_fecha']),
            row['numero_factura'],
            row['factura_real'] or '',
            row['tipo_comprobante'] or '',
            row['letra_fiscal'] or '',
            row['vendedor'] or '',
            row['combustible'] or '',
            row['litros'],
            yes_no_blank(row['pago_app_ypf']),
            row['chances'] or '',
            row.get('device_token') or '',
            row.get('ip_registro') or '',
            row.get('user_agent') or '',
            'Si' if row.get('sospecha_dispositivo') else 'No',
            row['nombre'],
            row['apellido'],
            row['dni'] or '',
            row['telefono'],
            row['email'],
            row['detalle_validacion'] or '',
            str(row['consulta_at'])[:19] if row['consulta_at'] else '',
            row['conteo_id'],
            repetition if ponderado and row['estado'] == 'APROBADO' else '',
        ])
    salida = BytesIO()
    wb.save(salida)
    salida.seek(0)
    suffix = estado.lower() if estado else 'general'
    if incluir_archivados:
        suffix += '_archivado'
    if ponderado:
        suffix += '_ponderado'
    return Response(
        salida.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment;filename=sorteo_{suffix}.xlsx'},
    )


@app.route('/<int:estacion_id>', methods=['GET', 'POST'])
@app.route('/sorteo/<int:estacion_id>', methods=['GET', 'POST'])
@app.route('/participar/<int:estacion_id>', methods=['GET', 'POST'])
def cliente_sorteo(estacion_id):
    ensure_config(estacion_id)
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('SELECT nombre FROM estaciones WHERE id = %s', (estacion_id,))
    estacion = c.fetchone()
    c.execute('SELECT * FROM sorteo_config WHERE estacion_id = %s', (estacion_id,))
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
                ticket_fecha = parse_ticket_date(request.form['fecha_ticket'])
                promo_desde, promo_hasta = get_active_promo_bounds(config)
                if ticket_fecha < promo_desde or ticket_fecha > promo_hasta:
                    raise ValueError('La fecha del ticket esta fuera de la promocion activa.')
                factura = normalize_invoice_number(request.form.get('numero_factura'))
                device_token = (request.form.get('device_token') or '').strip()
                user_agent = request.headers.get('User-Agent', '')
                ip_registro = get_client_ip()
                sospecha = count_device_registrations(c, estacion_id, config, device_token) >= 2
                estado_inicial = 'PENDIENTE'
                detalle = 'Esperando validacion.' if not sospecha else 'Esperando validacion. El dispositivo sera revisado si la factura matchea.'
                c.execute('''
                    INSERT INTO sorteo_participantes
                    (estacion_id, ticket_fecha, ticket_hora, numero_factura, nombre, apellido, dni, telefono, email, estado, device_token, ip_registro, user_agent, sospecha_dispositivo, detalle_validacion)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    estacion_id,
                    ticket_fecha,
                    datetime.combine(ticket_fecha, datetime.min.time()),
                    factura['canonical'],
                    request.form['nombre'].strip(),
                    request.form['apellido'].strip(),
                    request.form.get('dni', '').strip(),
                    request.form['telefono'].strip(),
                    request.form['email'].strip().lower(),
                    estado_inicial,
                    device_token,
                    ip_registro,
                    user_agent,
                    sospecha,
                    detalle,
                ))
                conn.commit()
                mensaje = 'Tu cupon quedo registrado. Si la factura coincide, pasara a aprobado; si detectamos algo raro con el dispositivo, quedara en revision.'
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                error = 'Ese ticket ya fue registrado para esta estacion.'
            except ValueError as exc:
                error = str(exc)
            except Exception as exc:
                conn.rollback()
                error = f'No se pudo registrar la participacion: {exc}'
    conn.close()
    return render_template('sorteo_cliente.html', estacion=estacion, mensaje=mensaje, error=error, detenido=config and config['detenido'])


init_db()

if os.environ.get('SORTEO_DISABLE_SCHEDULER') != '1':
    threading.Thread(target=scheduler_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('SORTEO_PORT', '5055')))
