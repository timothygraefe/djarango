#
# base.py
#
# Timothy Graefe, Javamata LLC
#

import logging
import warnings

# Django imports
from django.conf import settings
from django.db.utils import DatabaseError
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.base.validation import BaseDatabaseValidation
from django.db.backends.dummy.base import complain, ignore

# Arango Python driver (python-arango) imports.
from arango            import ArangoClient
from arango.exceptions import ServerConnectionError

logger = logging.getLogger('django.db.backends.arangodb')

from .client        import Database, DatabaseClient
from .features      import DatabaseFeatures
from .operations    import DatabaseOperations
from .creation      import DatabaseCreation
from .introspection import DatabaseIntrospection
from .schema        import DatabaseSchemaEditor


# Provide a cursor wrapper and database wrapper for the ArangoDB database.
# Both are built on top of the python-arango driver for ArangoDB.

#
# Define a cursor that is associated with the currently open connections.
# It will need to translate from SQL commands to AQL, and then send the
# requests via the python-arango driver.
#
class AdbCursorWrapper():
    _conn = None
    rowcount = 0
    query_cursor = None

    def __init__(self, connection):
        # connection is an ArangoDB (python driver) client StandardDatabase
        self._conn = connection
        self.rowcount = 0
        self.query_cursor = None

    def __enter__(self):
        if self._conn is None:
            logger.debug("AdbCursorWrapper __enter__: null _conn")
        return self

    def __exit__(self, arg1, arg2, arg3):
        if self._conn is None:
            logger.debug("AdbCursorWrapper __exit__: null _conn")
        return self

    def cursor_test_sql(self, sql):
        logger.debug("\nAdbCursorWrapper(): cursor_test_sql SQL=\"{sql}\"")
        self._conn.test_sql(sql)

    def execute(self, sql, params = None):
        logger.debug(f"\nAdbCursorWrapper(): execute SQL=\"{sql}\"")
        self.query_cursor = self._conn.aql.execute(query=sql)
        self.rowcount = self.query_cursor._stats['modified']
        return self

    def execute_many(self, sql, param_list = None):
        logger.debug(f"\nAdbCursorWrapper({self.cursor_id}): execute_many SQL=\"{sql}\"")
        self.query_cursor = self._conn.aql.execute_many(query=sql)
        self.rowcount = self.query_cursor._stats['modified']

    def batch(self):
        if not self.query_cursor == None:
            return self.query_cursor.batch()
        return []

    def close(self):
        if not self.query_cursor == None:
            self.query_cursor.close()
            self.query_cursor = None

    def empty(self):
        if not self.query_cursor == None:
            return self.query_cursor.empty()
        return False

    def fetchone(self):
        if self.query_cursor.empty():
            return False

        return list(self.query_cursor.pop().values())


#
# Provide a "DatabaseWrapper" for the underlying ArangoDB database.
# The DB is accessed via python-arango Python driver. This driver is actively
# developed and works with this Django integration, but is not directly
# supported by ArangoDB.
#
class DatabaseWrapper(BaseDatabaseWrapper):
    """Represent a database connection."""
    ops           = DatabaseOperations
    vendor        = 'arangodb'
    display_name  = 'ArangoDB'
    queries_limit = 9000

    Database            = Database()

    SchemaEditorClass   = DatabaseSchemaEditor

    client_class        = DatabaseClient
    creation_class      = DatabaseCreation
    features_class      = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class           = DatabaseOperations
    validation_class    = BaseDatabaseValidation

    _adbcursor          = None

    # Mapping of Field objects to their column types.
    data_types = {
        'AutoField'                 : 'serial',
        'BigAutoField'              : 'bigserial',
        'BinaryField'               : 'bytea',
        'BooleanField'              : 'boolean',
        'CharField'                 : 'varchar(%(max_length)s)',
        'DateField'                 : 'date',
        'DateTimeField'             : 'timestamp with time zone',
        'DecimalField'              : 'numeric(%(max_digits)s, %(decimal_places)s)',
        'DurationField'             : 'interval',
        'FileField'                 : 'varchar(%(max_length)s)',
        'FilePathField'             : 'varchar(%(max_length)s)',
        'FloatField'                : 'double precision',
        'IntegerField'              : 'integer',
        'BigIntegerField'           : 'bigint',
        'IPAddressField'            : 'inet',
        'GenericIPAddressField'     : 'inet',
        'NullBooleanField'          : 'boolean',
        'OneToOneField'             : 'integer',
        'PositiveIntegerField'      : 'integer',
        'PositiveSmallIntegerField' : 'smallint',
        'SlugField'                 : 'varchar(%(max_length)s)',
        'SmallIntegerField'         : 'smallint',
        'TextField'                 : 'text',
        'TimeField'                 : 'time',
        'UUIDField'                 : 'uuid',
    }

    # Mapping of Field objects to their SQL suffix such as AUTOINCREMENT.
    data_types_suffix = {}

    # Mapping of Field objects to their SQL for CHECK constraints.
    data_type_check_constraints = {
        'PositiveIntegerField': '"%(column)s" >= 0',
        'PositiveSmallIntegerField': '"%(column)s" >= 0',
    }

    operators = {
        'in': 'IN [%s]',
        'exact': '== %s',
        'iexact': 'LIKE %s',
        'contains': 'LIKE %s',
        'icontains': 'LIKE %s',
        'regex': '=~ %s',
        'iregex': '=~ %s',
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': 'LIKE %s',
        'endswith': 'LIKE %s',
        'istartswith': 'LIKE %s',
        'iendswith': 'LIKE %s',
        # Array Operators:
        'allin': 'ALL IN %s'
    }

    def get_connection_params(self):
        if self.Database.ready():
            return Database.conn_params

        # Use the Database client singleton imported from .client to get the params.
        return self.Database.get_connection_params(self.settings_dict)

    def get_new_connection(self, conn_params)->ArangoClient:
        # Database.connect returns Arango Python driver DB instance.
        # The DB instance contains a connection to the DB: Database._conn, that
        # will be established during the call to connect().
        # The base class stores the connection in self.connection
        return self.Database.connect(**conn_params)

    def init_connection_state(self):
        """Initializes the database connection settings."""
        # Initialization of the DB connection is handled in get_new_connection()
        pass

    def create_cursor(self, name):
        """Creates a cursor. Assumes that a connection is established."""
        if self._adbcursor == None:
            self._adbcursor = AdbCursorWrapper(self.connection)
        return self._adbcursor

    def chunked_cursor(self):
        raise NotImplementedError("ArangoClient Database Chunked Cursor not yet implemented")

    def adbcursor(self):
        if self._adbcursor == None:
            self._adbcursor = AdbCursorWrapper(self.connection)
        return self._adbcursor

    def set_autocommit(self, autocommit):
        """
        Backend-specific implementation to enable or disable autocommit.
        """
        logger.debug("set_autocommit(autocommit={})".format(autocommit))
        #warnings.warn("_set_autocommit() not set", )

    # ##### Backend-specific methods for creating connections #####

    def ensure_connection(self):
        """
        Guarantees that a connection to the database is established.
        """
        if (self.connection is None) or (not self.Database.ready()):
            with self.wrap_database_errors:
                self.connect()
        else:
            try:
                self.Database.verify()
            except AttributeError as err:
                raise err
            except ServerConnectionError as err:
                raise ServerConnectionError(f"bad connection: {err}")
            except Exception as err:
                raise err

    # ##### Generic wrappers for PEP-249 connection methods #####

    def cursor(self):
        """Create a cursor, opening a connection if necessary."""
        if not self.Database.ready():
            self.connect()

        if self._adbcursor is None:
            self._cursor()

        return self._adbcursor

    def _close(self):
        self.Database.close()

    # ##### Generic transaction management methods #####

    def set_autocommit(self, autocommit, force_begin_transaction_with_broken_autocommit=False):
        """
        Enable or disable autocommit.

        The usual way to start a transaction is to turn autocommit off.
        SQLite does not properly start a transaction when disabling
        autocommit. To avoid this buggy behavior and to actually enter a new
        transaction, an explcit BEGIN is required. Using
        force_begin_transaction_with_broken_autocommit=True will issue an
        explicit BEGIN with SQLite. This option will be ignored for other
        backends.
        """
        # set_autocommit() is not yet supported in djarango.

        logger.debug("set_autocommit(autocommit={}, force={})".
            format(autocommit, force_begin_transaction_with_broken_autocommit))
        #warnings.warn("set_autocommit() not set", )


    # Utility methods
    def create_collection(self, name):
        if self.Database.ready():
            return self.Database.create_collection(name)
        return None

    def get_collection(self, name):
        if self.Database.ready():
            return self.Database.get_collection(name)
        return None

    def get_collections(self):
        return self.Database.get_collections()

    def delete_all_collections(self):
        if self.Database.ready():
            self.Database.delete_all_collections()

    def delete_collection(self, name):
        if self.Database.ready():
            self.Database.delete_collection(name)

    def get_collection_docs(self, name):
        if self.Database.ready():
            return self.Database.get_collection_docs(name)
        return None

    def delete_document(self, collection, key):
        if self.Database.ready():
            self.Database.delete_document(collection, key)

    def get_document(self, collection, key):
        if self.Database.ready():
            self.Database.get_document(collection, key)

    def has_graph(self, name):
        if self.Database.ready():
            return self.Database.has_graph(name)
        return False

    def graph(self, name):
        if self.Database.ready():
            return self.Database.graph(name)
        return None

    def graphs(self):
        if self.Database.ready():
            return self.Database.graphs()
        return None

    def create_graph(self, name, eds):
        if self.Database.ready():
            return self.Database.create_graph(name, eds)
        return None

    def create_vertex_collection(self, name):
        if self.Database.ready():
            return self.Database.create_vertex_collection(name)
        return None

# base.py
