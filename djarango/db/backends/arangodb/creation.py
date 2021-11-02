#
# creation.py
#
# Timothy Graefe, Javamata LLC, Nov 2021
#
from django.db.backends.base.creation import BaseDatabaseCreation

# Needed to link into backend options.
class DatabaseCreation(BaseDatabaseCreation):
    pass

# creation.py
