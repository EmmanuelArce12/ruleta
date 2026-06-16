from werkzeug.middleware.dispatcher import DispatcherMiddleware

from app import app as ruleta_app
from sorteo_electrodomesticos import app as sorteo_app


application = DispatcherMiddleware(ruleta_app, {
    "/sorteo": sorteo_app,
})

