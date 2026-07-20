"""Import all models so Base.metadata knows about all tables.
Import this module before calling init_db().
"""
from orm.user import User, VerificationCode  # noqa: F401
from orm.entitlement import Entitlement  # noqa: F401
from orm.order import Order  # noqa: F401
from orm.points import Points, PointsLog  # noqa: F401
from orm.invite import Invite  # noqa: F401
from orm.user_data import ChartRecord, VerificationRecord, VerificationSessionModel  # noqa: F401
