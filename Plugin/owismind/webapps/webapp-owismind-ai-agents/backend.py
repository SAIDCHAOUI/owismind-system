# OWIsMind WebApp backend — thin bootstrap.
#
# All logic lives in python-lib/owismind/ (api / storage / security). DSS injects
# the Flask `app` object via the customwebapp star-import; here we only wire the
# OWIsMind API blueprint onto it. No business/SQL logic in this file.
from dataiku.customwebapp import *  # noqa: F401,F403  (provides the Flask `app`)

from owismind.api.routes import register_routes

register_routes(app)  # noqa: F405  (`app` comes from the star-import above)
